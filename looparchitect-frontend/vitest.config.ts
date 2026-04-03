import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
      // Resolve next/navigation to a lightweight mock so tests don't need
      // the full Next.js package installed
      "next/navigation": resolve(
        __dirname,
        "./src/test/__mocks__/next-navigation.ts"
      ),
    },
  },
});
