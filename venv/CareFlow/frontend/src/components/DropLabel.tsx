import { useState, type ReactNode } from "react";

type Props = {
  /** File picker MIME / extension filter (forwarded to <input>) */
  accept?: string;
  /** Allow multiple files */
  multiple?: boolean;
  /** Called whenever files are picked (via click or drop) */
  onFiles: (files: File[]) => void;
  /** Optional extra filter; return false to reject a dropped file silently */
  acceptFile?: (file: File) => boolean;
  /** Outer className applied to the <label> when NOT dragging */
  className?: string;
  /** Outer className applied to the <label> when dragging over */
  draggingClassName?: string;
  /** Inner content (preview / placeholder) */
  children: ReactNode;
};

/**
 * Drag-and-drop file label that also acts as a native file picker.
 * Used across α / β / γ / θ upload UIs for a consistent UX.
 */
export default function DropLabel({
  accept,
  multiple = false,
  onFiles,
  acceptFile,
  className = "",
  draggingClassName = "",
  children,
}: Props) {
  const [dragging, setDragging] = useState(false);

  const handle = (list: FileList | null | undefined) => {
    if (!list || list.length === 0) return;
    let arr = Array.from(list);
    if (acceptFile) arr = arr.filter(acceptFile);
    if (arr.length === 0) return;
    onFiles(multiple ? arr : [arr[0]]);
  };

  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        if (!dragging) setDragging(true);
      }}
      onDragLeave={(e) => {
        // ignore bubbling from children
        if (e.currentTarget.contains(e.relatedTarget as Node)) return;
        setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        handle(e.dataTransfer?.files);
      }}
      className={`${className} ${dragging ? draggingClassName : ""}`.trim()}
    >
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        className="hidden"
        onChange={(e) => handle(e.target.files)}
      />
      {children}
    </label>
  );
}
