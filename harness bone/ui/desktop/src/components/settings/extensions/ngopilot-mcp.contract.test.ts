import { describe, expect, it } from 'vitest';
import bundledExtensions from './bundled-extensions.json';

describe('NGOPilotMCP bundled extension', () => {
  it('is the enabled default NGO capability', () => {
    const extension = bundledExtensions.find((item) => item.id === 'ngopilot');
    const developer = bundledExtensions.find((item) => item.id === 'developer');

    expect(extension).toEqual(
      expect.objectContaining({
        name: 'NGOPilot',
        enabled: true,
        type: 'stdio',
        cmd: 'ngopilot-mcp',
        args: ['serve', '--transport', 'stdio'],
        timeout: 2100,
        bundled: true,
      })
    );
    expect(extension?.env_keys).toEqual([]);
    expect(developer?.enabled).toBe(false);
  });
});
