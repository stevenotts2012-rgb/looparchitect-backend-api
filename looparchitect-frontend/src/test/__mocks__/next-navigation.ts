/**
 * Minimal mock for next/navigation used in tests.
 * Only exports what the GeneratePage component actually imports.
 */
import { vi } from "vitest";

export const useSearchParams = vi.fn(() => ({
  get: vi.fn().mockReturnValue(null),
}));

export const useRouter = vi.fn(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}));
