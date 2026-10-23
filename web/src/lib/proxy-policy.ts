/**
 * Routes that can create canonical financial events or import commands.
 *
 * The current proxy has service-to-service authentication only. Until the API
 * derives an operator from an authenticated user session, these mutations must
 * not be exposed through the browser proxy: a caller could otherwise forge the
 * legacy free-text reviewer identity.
 */
export function isBlockedFinancialMutation(
  method: string,
  pathSegments: readonly string[],
): boolean {
  if (method.toUpperCase() !== "POST") return false;
  const [scope, command] = pathSegments;
  return scope === "commands" && (command === "approve-batch" || command === "dry-run-import");
}
