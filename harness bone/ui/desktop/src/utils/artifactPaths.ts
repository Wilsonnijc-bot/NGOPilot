const TENANT_FILE_PATH_PATTERN = /\/data\/tenants\/[^\r\n\"'`<>\[\]{}|\\]+/g;
const TRAILING_PROSE_PUNCTUATION = /[),.;:!?]+$/;
const INTERNAL_WORKFLOW_PATH_SEGMENTS = [
  '/inputs/',
  '/intermediate/',
  '/logs/',
  '/runtimes/',
  '/app-data/',
];

export interface ArtifactPathMatch {
  path: string;
  filename: string;
  start: number;
  end: number;
}

export function artifactDownloadsEnabled(): boolean {
  return window.appConfig?.get('NGOPILOT_CLOUD') === true;
}

export function artifactFilename(path: string): string {
  const encoded = path.split('/').pop() || 'download';
  try {
    return decodeURIComponent(encoded);
  } catch {
    return encoded;
  }
}

export function artifactFilesystemPath(path: string): string {
  try {
    return decodeURIComponent(path);
  } catch {
    return path;
  }
}

export function findArtifactPaths(text: string): ArtifactPathMatch[] {
  const matches: ArtifactPathMatch[] = [];

  for (const match of text.matchAll(TENANT_FILE_PATH_PATTERN)) {
    const matchedText = match[0];
    const path = matchedText.trimEnd().replace(TRAILING_PROSE_PUNCTUATION, '');
    const start = match.index ?? 0;
    const filename = artifactFilename(path);

    if (INTERNAL_WORKFLOW_PATH_SEGMENTS.some((segment) => path.includes(segment))) continue;

    matches.push({
      path,
      filename,
      start,
      end: start + path.length,
    });
  }

  return matches;
}

export function isArtifactPath(value: string): boolean {
  const matches = findArtifactPaths(value);
  return matches.length === 1 && matches[0].start === 0 && matches[0].end === value.length;
}
