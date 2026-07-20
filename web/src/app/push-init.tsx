"use client";

import { useEffect } from "react";
import { fetchPushConfig, subscribeToPush } from "@/lib/push-config";

export function PushInitScript() {
  useEffect(() => {
    let mounted = true;

    async function init() {
      try {
        const config = await fetchPushConfig();
        if (!config.enabled || !mounted) return;
        await subscribeToPush(config);
      } catch {
        // Push registration failure is non-fatal — the console works
        // without push. The error is swallowed intentionally.
      }
    }

    init();
    return () => {
      mounted = false;
    };
  }, []);

  return null;
}
