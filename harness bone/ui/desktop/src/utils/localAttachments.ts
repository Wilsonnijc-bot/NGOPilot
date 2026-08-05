const LOCAL_ATTACHMENT_HEADER = 'Local attachment paths (JSON; use exact values):';

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
