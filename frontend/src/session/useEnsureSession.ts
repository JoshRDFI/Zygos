import { useEffect } from "react";
import { useSessionStore } from "./sessionStore";

/** Start the app-lifetime session exactly once. No teardown: the session lives
 *  for the app's lifetime, and start() is idempotent so StrictMode's double
 *  effect-invoke does not create a second session. */
export function useEnsureSession(): void {
  useEffect(() => {
    useSessionStore.getState().start();
  }, []);
}
