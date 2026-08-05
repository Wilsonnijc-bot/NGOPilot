import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IntlTestWrapper } from '../i18n/test-utils';
import type {
  NotificationEvent,
  ToolRequestMessageContent,
  ToolResponseMessageContent,
} from '../types/message';
import ToolCallWithResponse from './ToolCallWithResponse';

const toolRequest: ToolRequestMessageContent = {
  type: 'toolRequest',
  id: 'tool-1',
  toolCall: {
    status: 'success',
    value: {
      name: 'developer__shell',
      arguments: {
        command: 'build',
      },
    },
  },
};

const liveOutputNotification: NotificationEvent = {
  type: 'Notification',
  request_id: 'tool-1',
  message: {
    method: 'goose/live_output',
    params: {
      sequence: 1,
      chunks: [
        {
          stream: 'stdout',
          output: 'starting\n',
        },
        {
          stream: 'stderr',
          output: 'checking\n',
        },
      ],
      truncated: false,
    },
  },
};

const toolResponse: ToolResponseMessageContent = {
  type: 'toolResponse',
  id: 'tool-1',
  toolResult: {
    status: 'success',
    value: {
      content: [
        {
          type: 'text',
          text: 'final result',
        },
      ],
      isError: false,
    },
  },
};

function renderToolCall(response?: ToolResponseMessageContent) {
  return render(
    <ToolCallWithResponse
      isCancelledMessage={false}
      toolRequest={toolRequest}
      toolResponse={response}
      notifications={[liveOutputNotification]}
      isStreamingMessage={!response}
      isPendingApproval={false}
    />,
    { wrapper: IntlTestWrapper }
  );
}

describe('ToolCallWithResponse live output', () => {
  beforeEach(() => {
    vi.mocked(window.electron.getSetting).mockResolvedValue('detailed');
  });

  it('renders raw live output while running and replaces it with the final result', async () => {
    const { rerender } = renderToolCall();

    expect(screen.getByText(/starting/)).toHaveTextContent('starting checking');
    expect(screen.queryByText(/stdout|stderr/)).not.toBeInTheDocument();

    rerender(
      <ToolCallWithResponse
        isCancelledMessage={false}
        toolRequest={toolRequest}
        toolResponse={toolResponse}
        notifications={[liveOutputNotification]}
        isStreamingMessage={false}
        isPendingApproval={false}
      />
    );

    expect(screen.queryByText(/starting/)).not.toBeInTheDocument();
    expect(await screen.findByText('final result')).toBeInTheDocument();
  });

  it('renders file paths in tool output as download links in the cloud app', async () => {
    const path = '/data/tenants/user/workflow/jobs/job-1/outputs/report.xlsx';
    const sourcePath = '/data/tenants/user/workflow/jobs/job-1/inputs/source.xlsx';
    const originalAppConfig = window.appConfig;
    window.appConfig = {
      ...originalAppConfig,
      get: vi.fn((key: string) => (key === 'NGOPILOT_CLOUD' ? true : undefined)),
    };
    const response: ToolResponseMessageContent = {
      ...toolResponse,
      toolResult: {
        status: 'success',
        value: {
          content: [
            {
              type: 'text',
              text: JSON.stringify({ output_path: path, source_path: sourcePath }),
            },
          ],
          isError: false,
        },
      },
    };

    try {
      renderToolCall(response);
      const link = await screen.findByRole('link', { name: 'Download report.xlsx' });
      expect(link).toHaveAttribute('href', path);
      expect(screen.queryByRole('link', { name: 'Download source.xlsx' })).not.toBeInTheDocument();
    } finally {
      window.appConfig = originalAppConfig;
    }
  });

  it('renders every artifact occurrence from the production MCP payload as a download control', async () => {
    const path =
      '/data/tenants/e6300d72-5803-4b89-b56d-d63da2934748/workflow/jobs/careflow_paper_forms_to_excel/job_bff6e06dc3fb4f2bbf226a188af1fb4b/outputs/11edf68c5fde_batch_1_20260805_071743.xlsx';
    const sourcePath =
      '/data/tenants/e6300d72-5803-4b89-b56d-d63da2934748/workflow/jobs/careflow_paper_forms_to_excel/job_bff6e06dc3fb4f2bbf226a188af1fb4b/inputs/completed_form_image_001_64211101c04e.png';
    const nativePath =
      '/data/tenants/e6300d72-5803-4b89-b56d-d63da2934748/workflow/app-data/careflow/exports/batch_1_20260805_071743.xlsx';
    const originalAppConfig = window.appConfig;
    window.appConfig = {
      ...originalAppConfig,
      get: vi.fn((key: string) => (key === 'NGOPILOT_CLOUD' ? true : undefined)),
    };
    const response: ToolResponseMessageContent = {
      ...toolResponse,
      toolResult: {
        status: 'success',
        value: {
          content: [
            {
              type: 'text',
              text: JSON.stringify({
                schema_version: '1.0',
                tool: 'careflow_paper_forms_to_excel',
                result: { output_path: path, source_path: sourcePath },
                artifacts: [{ path, native_path: nativePath }],
              }),
            },
          ],
          isError: false,
        },
      },
    };

    try {
      renderToolCall(response);
      const links = await screen.findAllByRole('link', {
        name: 'Download 11edf68c5fde_batch_1_20260805_071743.xlsx',
      });
      expect(links).toHaveLength(2);
      expect(links.every((link) => link.getAttribute('href') === path)).toBe(true);
      expect(screen.queryByRole('link', { name: /completed_form_image/ })).not.toBeInTheDocument();
      expect(
        screen.queryByRole('link', { name: 'Download batch_1_20260805_071743.xlsx' })
      ).not.toBeInTheDocument();
    } finally {
      window.appConfig = originalAppConfig;
    }
  });
});
