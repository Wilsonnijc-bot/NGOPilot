import { describe, expect, it } from 'vitest';
import { appendLocalAttachmentPaths, shouldSendImageToModel } from './localAttachments';

describe('appendLocalAttachmentPaths', () => {
  it('adds exact file paths as JSON attachment context', () => {
    expect(
      appendLocalAttachmentPaths('Turn these forms into Excel', [
        '/tmp/visit form 1.png',
        '/tmp/visit-form-2.jpg',
      ])
    ).toBe(
      'Turn these forms into Excel\n\nLocal attachment paths (JSON; use exact values):\n["/tmp/visit form 1.png","/tmp/visit-form-2.jpg"]'
    );
  });

  it('deduplicates paths and leaves text unchanged without attachments', () => {
    expect(appendLocalAttachmentPaths('', ['/tmp/form.png', '/tmp/form.png'])).toBe(
      'Local attachment paths (JSON; use exact values):\n["/tmp/form.png"]'
    );
    expect(appendLocalAttachmentPaths('Hello', [])).toBe('Hello');
  });

  it('sends only pathless clipboard images to the language model', () => {
    expect(shouldSendImageToModel('/tmp/form.png')).toBe(false);
    expect(shouldSendImageToModel()).toBe(true);
  });
});
