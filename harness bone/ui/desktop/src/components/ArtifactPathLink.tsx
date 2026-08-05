import React, { useMemo, useState } from 'react';
import { Download } from 'lucide-react';
import { defineMessages, useIntl } from '../i18n';
import {
  artifactDownloadsEnabled,
  artifactFilename,
  artifactFilesystemPath,
  findArtifactPaths,
} from '../utils/artifactPaths';

const i18n = defineMessages({
  download: {
    id: 'artifactPathLink.download',
    defaultMessage: 'Download {filename}',
  },
  preparing: {
    id: 'artifactPathLink.preparing',
    defaultMessage: 'Preparing download...',
  },
  failedTitle: {
    id: 'artifactPathLink.failedTitle',
    defaultMessage: 'Download Failed',
  },
  failedMessage: {
    id: 'artifactPathLink.failedMessage',
    defaultMessage: 'The generated file could not be downloaded.',
  },
});

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
  const intl = useIntl();
  const [isDownloading, setIsDownloading] = useState(false);
  const filesystemPath = artifactFilesystemPath(path);
  const filename = artifactFilename(filesystemPath);
  const color = inverted
    ? 'border-gray-600 bg-gray-800 text-gray-100 hover:bg-gray-700 focus-visible:ring-gray-400'
    : 'border-border-primary bg-background-secondary text-text-primary hover:bg-background-primary focus-visible:ring-border-primary';

  const handleDownload = async (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (isDownloading) return;

    setIsDownloading(true);
    try {
      await window.electron.openExternal(filesystemPath);
    } catch {
      await window.electron.showMessageBox({
        type: 'error',
        buttons: ['OK'],
        title: intl.formatMessage(i18n.failedTitle),
        message: intl.formatMessage(i18n.failedMessage),
        detail: filename,
      });
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <a
      href={filesystemPath}
      title={filesystemPath}
      aria-label={`Download ${filename}`}
      aria-busy={isDownloading}
      data-artifact-path={filesystemPath}
      className={`my-0.5 inline-flex max-w-full cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 align-middle font-sans text-xs font-medium no-underline transition-colors focus-visible:outline-none focus-visible:ring-2 disabled:pointer-events-none ${color}`}
      onClick={(event) => void handleDownload(event)}
    >
      <Download className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
      <span className={compact ? 'truncate' : 'break-all'}>
        {isDownloading
          ? intl.formatMessage(i18n.preparing)
          : intl.formatMessage(i18n.download, {
              filename: children ?? filename,
            })}
      </span>
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
