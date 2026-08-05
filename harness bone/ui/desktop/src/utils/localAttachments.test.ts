import { describe, expect, it, vi } from 'vitest';
import {
  appendLocalAttachmentPaths,
  getLocalAttachmentPath,
  isLocalAttachmentSubmittable,
  resolveLocalAttachmentPath,
  shouldSendImageToModel,
} from './localAttachments';

describe('appendLocalAttachmentPaths', () => {
  it('adds exact file paths as JSON attachment context', () => {
    expect(
      appendLocalAttachmentPaths('Turn these forms into Excel', [
        '/tmp/visit form 1.png',
        '/tmp/visit-form-2.jpg',
      ])
    ).toBe(
      'Turn these forms into Excel\n\nAttachments:\n["/tmp/visit form 1.png","/tmp/visit-form-2.jpg"]'
    );
  });

  it('deduplicates paths and leaves text unchanged without attachments', () => {
    expect(appendLocalAttachmentPaths('', ['/tmp/form.png', '/tmp/form.png'])).toBe(
      'Attachments:\n["/tmp/form.png"]'
    );
    expect(appendLocalAttachmentPaths('Hello', [])).toBe('Hello');
  });

  it('gets a path for pasted files through the platform bridge', () => {
    const file = new File(['image'], 'form.png', { type: 'image/png' });
    const getPathForFile = vi.fn(() => ' /tmp/form.png ');

    expect(getLocalAttachmentPath(file, getPathForFile)).toBe('/tmp/form.png');
    expect(getPathForFile).toHaveBeenCalledWith(file);
    expect(getLocalAttachmentPath(file, () => '')).toBeUndefined();
  });

  it('persists a pathless clipboard file and returns its absolute path', async () => {
    const file = new File(['image'], 'form.png', { type: 'image/png' });
    const persistAttachment = vi.fn(async () => ' /tmp/ngopilot/form.png ');

    await expect(resolveLocalAttachmentPath(file, () => '', persistAttachment)).resolves.toBe(
      '/tmp/ngopilot/form.png'
    );
    expect(persistAttachment).toHaveBeenCalledWith(
      'form.png',
      'image/png',
      expect.any(ArrayBuffer)
    );
  });

  it('does not persist a file that already has a path', async () => {
    const file = new File(['image'], 'form.png', { type: 'image/png' });
    const persistAttachment = vi.fn(async () => '/tmp/fallback.png');

    await expect(
      resolveLocalAttachmentPath(file, () => '/tmp/form.png', persistAttachment)
    ).resolves.toBe('/tmp/form.png');
    expect(persistAttachment).not.toHaveBeenCalled();
  });

  it('persists when the platform path bridge throws', async () => {
    const file = new File(['image'], 'form.png', { type: 'image/png' });
    const persistAttachment = vi.fn(async () => '/tmp/fallback.png');

    await expect(
      resolveLocalAttachmentPath(
        file,
        () => {
          throw new Error('path unavailable');
        },
        persistAttachment
      )
    ).resolves.toBe('/tmp/fallback.png');
  });

  it('returns no path when both platform bridges fail', async () => {
    const file = new File(['image'], 'form.png', { type: 'image/png' });

    await expect(
      resolveLocalAttachmentPath(
        file,
        () => '',
        async () => {
          throw new Error('persistence failed');
        }
      )
    ).resolves.toBeUndefined();
  });

  it('sends only pathless clipboard images to the language model', () => {
    expect(shouldSendImageToModel('/tmp/form.png')).toBe(false);
    expect(shouldSendImageToModel()).toBe(true);
  });

  it('keeps a path submittable when only its preview fails', () => {
    expect(
      isLocalAttachmentSubmittable({
        path: '/tmp/form.png',
        error: 'preview failed',
        isImage: true,
        isLoading: false,
      })
    ).toBe(true);
  });

  it('rejects failed pathless attachments', () => {
    expect(
      isLocalAttachmentSubmittable({
        error: 'path unavailable',
        isImage: true,
        isLoading: false,
      })
    ).toBe(false);
  });
});
