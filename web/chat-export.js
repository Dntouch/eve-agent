/* Local chat PNG export. html2canvas 1.4.1 is vendored separately (MIT).
 * PNG rows are compressed incrementally, avoiding a full-height browser canvas.
 */
(() => {
  "use strict";
  const crcTable = Uint32Array.from({ length: 256 }, (_, value) => {
    for (let bit = 0; bit < 8; bit++) value = (value & 1) ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    return value >>> 0;
  });

  function pngChunk(type, data = new Uint8Array()) {
    const bytes = new Uint8Array(data.length + 12);
    const view = new DataView(bytes.buffer);
    view.setUint32(0, data.length);
    bytes.set(new TextEncoder().encode(type), 4);
    bytes.set(data, 8);
    let crc = 0xffffffff;
    for (let index = 4; index < bytes.length - 4; index++) crc = crcTable[(crc ^ bytes[index]) & 255] ^ (crc >>> 8);
    view.setUint32(bytes.length - 4, (crc ^ 0xffffffff) >>> 0);
    return bytes;
  }

  async function encodePng(width, height, tiles) {
    if (typeof CompressionStream !== "function") throw new Error("Der PNG-Export benötigt einen aktuellen Browser mit CompressionStream-Unterstützung.");
    if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width > 0x7fffffff || height > 0x7fffffff) throw new Error("Die Bildmaße sind für das PNG-Format ungültig.");
    const header = new Uint8Array(13);
    const view = new DataView(header.buffer);
    view.setUint32(0, width); view.setUint32(4, height);
    header[8] = 8; header[9] = 6; // 8-bit RGBA, standard compression/filtering.
    const parts = [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), pngChunk("IHDR", header)];
    const compression = new CompressionStream("deflate");
    const writer = compression.writable.getWriter();
    const reader = compression.readable.getReader();
    const collect = (async () => {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        parts.push(pngChunk("IDAT", value));
      }
    })();
    collect.catch(() => {}); // Rejection is awaited below, including renderer failure.
    let rows = 0;
    try {
      for await (const tile of tiles) {
        if (tile.width !== width || !Number.isInteger(tile.height) || tile.height < 1 || tile.data.length !== width * tile.height * 4 || rows + tile.height > height) throw new Error("Ein Bildabschnitt hat ungültige Maße.");
        const stride = width * 4;
        const filtered = new Uint8Array((stride + 1) * tile.height);
        for (let row = 0; row < tile.height; row++) filtered.set(tile.data.subarray(row * stride, (row + 1) * stride), row * (stride + 1) + 1);
        await writer.write(filtered); // Each row uses PNG filter 0.
        rows += tile.height;
      }
      if (rows !== height) throw new Error("Der Chat wurde nicht vollständig gerendert.");
      await writer.close();
      await collect;
      parts.push(pngChunk("IEND"));
      return new Blob(parts, { type: "image/png" });
    } catch (error) {
      await writer.abort(error).catch(() => {});
      await collect.catch(() => {});
      throw error;
    } finally { reader.releaseLock(); writer.releaseLock(); }
  }

  async function loadConversation(fetchPage) {
    const messages = new Map();
    let before;
    let first;
    while (true) {
      const page = await fetchPage(before);
      if (!first) first = page;
      for (const message of page.messages || []) messages.set(message.id, message);
      if (!page.has_more) break;
      const oldest = Math.min(...(page.messages || []).map(message => message.ordinal));
      if (!Number.isFinite(oldest) || (before !== undefined && oldest >= before)) throw new Error("Der vollständige Chatverlauf konnte nicht geladen werden.");
      before = oldest;
    }
    const timeline = [
      ...messages.values(),
      ...(first.failures || []).map(failure_report => ({ created_at: failure_report.created_at, failure_report })),
    ].sort((a, b) => new Date(a.created_at) - new Date(b.created_at) || (a.ordinal ?? 0) - (b.ordinal ?? 0));
    return { conversation: first.conversation, timeline };
  }

  async function embedImages(root, headers) {
    await Promise.all([...root.querySelectorAll("img")].map(async image => {
      image.loading = "eager";
      const url = new URL(image.getAttribute("src"), document.baseURI);
      try {
        const response = await fetch(url.href, { headers: url.origin === location.origin ? headers : {}, credentials: url.origin === location.origin ? "same-origin" : "omit" });
        if (!response.ok) throw new Error(String(response.status));
        const blob = await response.blob();
        const source = await new Promise((resolve, reject) => {
          const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(reader.error); reader.readAsDataURL(blob);
        });
        image.src = source;
        await image.decode();
      } catch { throw new Error("Ein Bild im Chat konnte nicht geladen werden. Bitte prüfe seine Erreichbarkeit und versuche den Export erneut."); }
    }));
  }

  async function renderPng(root, { headers = {}, progress = () => {} } = {}) {
    if (typeof globalThis.html2canvas !== "function") throw new Error("Die lokale PNG-Exportbibliothek konnte nicht geladen werden.");
    await document.fonts.ready;
    await embedImages(root, headers);
    const width = Math.ceil(root.getBoundingClientRect().width);
    const height = Math.ceil(root.scrollHeight);
    async function* tiles() {
      for (let top = 0; top < height; top += 2048) {
        const size = Math.min(2048, height - top);
        const canvas = await globalThis.html2canvas(root, {
          scale: 1, width, height: size, y: top, backgroundColor: "#07131d", logging: false,
          scrollX: 0, scrollY: 0, useCORS: true,
        });
        try {
          const pixels = canvas.getContext("2d").getImageData(0, 0, width, size);
          yield { width, height: size, data: pixels.data };
        } finally { canvas.width = 0; canvas.height = 0; }
        progress(Math.round((top + size) / height * 100));
        await new Promise(resolve => setTimeout(resolve, 0));
      }
    }
    return encodePng(width, height, tiles());
  }

  globalThis.EveChatExport = Object.freeze({ loadConversation, renderPng, encodePng });
})();
