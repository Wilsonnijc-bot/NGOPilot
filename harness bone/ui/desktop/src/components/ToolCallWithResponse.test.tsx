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
});
