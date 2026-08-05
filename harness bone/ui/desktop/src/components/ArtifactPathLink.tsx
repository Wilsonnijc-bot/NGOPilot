import React, { useMemo } from 'react';
import { Download } from 'lucide-react';
import {
  artifactDownloadsEnabled,
  artifactFilename,
  artifactFilesystemPath,
  findArtifactPaths,
} from '../utils/artifactPaths';

interface ArtifactPathLinkProps {
  path: string;
  children?: React.ReactNode;
  compact?: boolean;
  inverted?: boolean;
}

export function ArtifactPathLink({
  path,
  children,
  compact = false,
  inverted = false,
}: ArtifactPathLinkProps) {
  const filesystemPath = artifactFilesystemPath(path);
  const filename = artifactFilename(filesystemPath);
  const color = inverted
    ? 'text-gray-100 decoration-gray-500 hover:decoration-gray-100 focus-visible:ring-gray-400'
    : 'text-text-primary decoration-border-primary hover:decoration-text-primary focus-visible:ring-border-primary';

  return (
    <a
      href={filesystemPath}
      title={filesystemPath}
      aria-label={`Download ${filename}`}
      data-artifact-path={filesystemPath}
      className={`inline-flex max-w-full items-center gap-1 align-baseline font-medium underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 ${color}`}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        void window.electron.openExternal(filesystemPath);
      }}
    >
      <Download className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
      <span className={compact ? 'truncate' : 'break-all'}>{children ?? filename}</span>
    </a>
  );
}

export function ArtifactText({ text }: { text: string }) {
  const matches = useMemo(
    () => (artifactDownloadsEnabled() ? findArtifactPaths(text) : []),
    [text]
  );

  if (matches.length === 0) return <>{text}</>;

  const content: React.ReactNode[] = [];
  let cursor = 0;
  for (const match of matches) {
    if (match.start > cursor) content.push(text.slice(cursor, match.start));
    content.push(<ArtifactPathLink key={`${match.start}:${match.path}`} path={match.path} />);
    cursor = match.end;
  }
  if (cursor < text.length) content.push(text.slice(cursor));

  return <>{content}</>;
}

export function ArtifactLinkList({ text }: { text: string }) {
  const matches = useMemo(() => {
    if (!artifactDownloadsEnabled()) return [];
    const unique = new Map<string, ReturnType<typeof findArtifactPaths>[number]>();
    for (const match of findArtifactPaths(text)) unique.set(match.path, match);
    return [...unique.values()];
  }, [text]);

  if (matches.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 border-b border-gray-700 bg-gray-800 px-3 py-2 font-sans text-xs text-gray-200">
      {matches.map((match) => (
        <ArtifactPathLink key={match.path} path={match.path} compact inverted />
      ))}
    </div>
  );
}
