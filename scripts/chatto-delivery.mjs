// Claims are recoverable until onDispatch persists the start of visible output.
// Once dispatch may have begun, only an acknowledgement is safe to repeat.
export function createDeliveryPump({ eve, send, signal, isConnected = () => true, onDelivered = () => {},
  sendTimeoutMs = 240000 }) {
  let busy = false;
  const acknowledgements = new Map();
  const call = (path, payload) => eve(path, payload,
    AbortSignal.any([signal, AbortSignal.timeout(10000)]));
  async function acknowledge(delivery, status, error) {
    // Retain only the ACK when the bridge is temporarily unavailable. Repeating
    // a confirmation must never invoke send() or execute the task again.
    const item = { delivery, status, error };
    acknowledgements.set(delivery.id, item);
    try {
      await call('/api/chatto/delivery-ack', {
        id: delivery.id, claim_token: delivery.claim_token, status, error,
      });
    } catch (failure) {
      // A revoked/expired claim cannot be repaired by repeating the same ACK.
      if (failure.code >= 400 && failure.code < 500) acknowledgements.delete(delivery.id);
      throw failure;
    }
    acknowledgements.delete(delivery.id);
    if (status === 'delivered') await onDelivered(delivery);
  }
  return async () => {
    if (busy || signal.aborted || !isConnected()) return;
    busy = true;
    try {
      for (const item of acknowledgements.values()) {
        await acknowledge(item.delivery, item.status, item.error);
      }
      const batch = await call('/api/chatto/deliveries', {});
      for (const delivery of batch.deliveries) {
        if (signal.aborted) return;
        let dispatched = false;
        let dispatchRequested = false;
        try {
          await send(delivery, async () => {
            dispatchRequested = true;
            if (delivery.claim_token) await call('/api/chatto/delivery-start', {
              id: delivery.id, claim_token: delivery.claim_token,
            });
            dispatched = true;
          }, AbortSignal.any([signal, AbortSignal.timeout(sendTimeoutMs)]));
        } catch (error) {
          // A lost dispatch-marker response must expire through the server's
          // claim recovery. Do not turn a possibly committed marker into retry.
          if (dispatchRequested && !dispatched) throw error;
          const permanent = error.permanent || [3, 5, 7, 9, 11, 12, 16].includes(error.code);
          const retry = delivery.claim_token && !permanent;
          await acknowledge(delivery, dispatched ? 'uncertain' : retry ? 'retry' : 'blocked',
            dispatched ? 'Send outcome uncertain' : retry ? 'Destination temporarily unavailable' : 'Destination validation failed');
          continue;
        }
        // Keep this outside the send catch: losing the ACK cannot undo a send.
        await acknowledge(delivery, 'delivered');
      }
    } finally { busy = false; }
  };
}
