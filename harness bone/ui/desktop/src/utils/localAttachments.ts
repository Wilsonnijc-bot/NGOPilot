const LOCAL_ATTACHMENT_HEADER = 'Attachments:';

export function getLocalAttachmentPath(
  file: File,
  getPathForFile: (file: File) => string
): string | undefined {
  const path = getPathForFile(file).trim();
  return path || undefined;
}

export async function resolveLocalAttachmentPath(
  file: File,
  getPathForFile: (file: File) => string,
  persistAttachment?: (fileName: string, contentType: string, data: ArrayBuffer) => Promise<string>
): Promise<string | undefined> {
  let existingPath: string | undefined;
  try {
    existingPath = getLocalAttachmentPath(file, getPathForFile);
  } catch {
    existingPath = undefined;
  }
  if (existingPath || !persistAttachment) {
    return existingPath;
  }

  try {
    const persistedPath = (
      await persistAttachment(file.name, file.type, await file.arrayBuffer())
    ).trim();
    return persistedPath || undefined;
  } catch {
    return undefined;
  }
}

export function shouldSendImageToModel(path?: string): boolean {
  return !path;
}

export function isLocalAttachmentSubmittable(attachment: {
  path?: string;
  dataUrl?: string;
  error?: string;
  isImage?: boolean;
  isLoading?: boolean;
}): boolean {
  if (attachment.isLoading) {
    return false;
  }
  if (attachment.path) {
    return true;
  }
  return attachment.isImage !== false && Boolean(attachment.dataUrl && !attachment.error);
}

export function appendLocalAttachmentPaths(text: string, paths: string[]): string {
  const uniquePaths = [...new Set(paths.filter((path) => path.length > 0))];
  if (uniquePaths.length === 0) {
    return text;
  }

  const attachmentContext = `${LOCAL_ATTACHMENT_HEADER}\n${JSON.stringify(uniquePaths)}`;
  return text ? `${text}\n\n${attachmentContext}` : attachmentContext;
}
