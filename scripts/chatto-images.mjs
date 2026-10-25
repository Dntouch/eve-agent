// Download only attachments authorized by Chatto's room-scoped asset API.
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);

export async function loadImages(server, message, signal) {
  const attachments = (message.attachments || []).filter(a => a.contentType?.startsWith('image/'));
  if (attachments.length > 4) throw new Error('Too many attached images');
  const images = [];
  for (const attachment of attachments) {
    const result = await server.readAttachment({ roomId: message.roomId, attachmentId: attachment.id }, {
      signal, maxImageSize: 2048, maxBytes: MAX_IMAGE_BYTES,
    });
    if (!IMAGE_TYPES.has(result.contentType) || !result.data.length || result.data.length > MAX_IMAGE_BYTES) {
      throw new Error('Unsupported attached image');
    }
    images.push(`data:${result.contentType};base64,${Buffer.from(result.data).toString('base64')}`);
  }
  return images;
}
