"""CPU-only, offline ONNX embeddings; no model server or GPU allocation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class LocalONNXEmbeddings:
    def __init__(self, config, root):
        self.model = config['model']
        directory = Path(config['model_dir']).expanduser()
        self.directory = directory if directory.is_absolute() else Path(root) / directory
        self.query_prefix = config.get('query_prefix', 'query: ')
        self.document_prefix = config.get('document_prefix', 'passage: ')
        self.threads = int(config.get('threads', 2))
        self.max_tokens = 512
        # Fingerprint the actual model/tokenizer, not the dialog endpoint.
        self.identity = json.dumps(['local-onnx-e5-mean-chunks-v1', self.model,
            file_digest(self.directory / 'model.onnx'), file_digest(self.directory / 'tokenizer.json'),
            self.query_prefix, self.document_prefix, self.max_tokens])
        self._lock = threading.Lock()
        self._session = None
        self._tokenizer = None

    def _load(self):
        if self._session is not None:
            return
        import onnxruntime as ort
        from tokenizers import Tokenizer
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = self.threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        session = ort.InferenceSession(str(self.directory / 'model.onnx'),
                                       sess_options=options, providers=['CPUExecutionProvider'])
        tokenizer = Tokenizer.from_file(str(self.directory / 'tokenizer.json'))
        tokenizer.enable_truncation(max_length=self.max_tokens, stride=0)
        # Pad each inference batch explicitly, rather than hardcoding token 0
        # (XLM-R uses pad token 1).
        self._pad_id = tokenizer.token_to_id('<pad>')
        if self._pad_id is None:
            raise RuntimeError('Embedding-Tokenizer hat kein Padding-Token')
        self._session, self._tokenizer = session, tokenizer

    def embed(self, texts, *, query=False):
        if not texts:
            return []
        from .memory_search import normalized
        import numpy as np
        with self._lock:
            try:
                self._load()
                prefix = self.query_prefix if query else self.document_prefix
                encoded = self._tokenizer.encode_batch([prefix + str(text) for text in texts])
                chunks = [(index, chunk) for index, item in enumerate(encoded)
                          for chunk in [item, *item.overflowing]]
                totals, weights = {}, {}
                for start in range(0, len(chunks), 8):
                    batch = chunks[start:start + 8]
                    width = max(len(item.ids) for _, item in batch)
                    ids = np.full((len(batch), width), self._pad_id, dtype=np.int64)
                    mask = np.zeros_like(ids)
                    for row, (_, item) in enumerate(batch):
                        ids[row, :len(item.ids)] = item.ids
                        mask[row, :len(item.ids)] = item.attention_mask
                    available = {'input_ids': ids, 'attention_mask': mask,
                                 'token_type_ids': np.zeros_like(ids)}
                    inputs = {item.name: available[item.name] for item in self._session.get_inputs()}
                    hidden = self._session.run(None, inputs)[0]
                    if hidden.ndim != 3 or hidden.shape[:2] != ids.shape:
                        raise RuntimeError('Embedding-Modell liefert keine Token-Repräsentationen')
                    # E5 model card: attention-masked mean pooling, then L2.
                    pooled = (hidden * mask[:, :, None]).sum(axis=1)
                    counts = mask.sum(axis=1)
                    for row, (owner, _) in enumerate(batch):
                        totals[owner] = totals.get(owner, 0) + pooled[row]
                        weights[owner] = weights.get(owner, 0) + counts[row]
                return [normalized((totals[index] / max(weights[index], 1)).tolist())
                        for index in range(len(texts))]
            except Exception as exc:
                raise RuntimeError('Lokale Embedding-Berechnung fehlgeschlagen: ' + type(exc).__name__) from exc


def create_embedding_client(config, root):
    if not config.get('model'):
        return None
    if config.get('backend', 'local_onnx') == 'local_onnx':
        return LocalONNXEmbeddings(config, root)
    from .memory_search import EmbeddingClient
    return EmbeddingClient(config)
