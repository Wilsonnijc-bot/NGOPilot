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
  const existingPath = getLocalAttachmentPath(file, getPathForFile);
  if (existingPath || !persistAttachment) {
    return existingPath;
  }

  const persistedPath = (
    await persistAttachment(file.name, file.type, await file.arrayBuffer())
  ).trim();
  return persistedPath || undefined;
}

export function shouldSendImageToModel(path?: string): boolean {
  return !path;
}

export function appendLocalAttachmentPaths(text: string, paths: string[]): string {
  const uniquePaths = [...new Set(paths.filter((path) => path.length > 0))];
  if (uniquePaths.length === 0) {
    return text;
  }

  const attachmentContext = `${LOCAL_ATTACHMENT_HEADER}\n${JSON.stringify(uniquePaths)}`;
  return text ? `${text}\n\n${attachmentContext}` : attachmentContext;
}
