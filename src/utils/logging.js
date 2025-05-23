

const { Pool } = require('pg');
const db = new Pool({ connectionString: process.env.SR_DATABASE_URL });

/**
 * Logs a structured agent action event to the agent_action_log table.
 * 
 * @param {Object} params - The event parameters
 * @param {string} params.source - Where the event came from (e.g. "slack", "gpt", "system")
 * @param {string} params.action_type - The type of action (e.g. "suggestion", "button_click", "job_retry")
 * @param {Object} params.action_detail - JSON-serializable object with event-specific metadata
 * @param {string|null} [params.user_id] - Slack user ID or null if system-generated
 * @param {string|null} [params.result] - Outcome of the action ("success", "error", etc.)
 * @param {string|null} [params.correlation_id] - Optional grouping ID for tracing chains of actions
 * @param {string|null} [params.notes] - Optional freeform notes
 */
async function logAgentAction({
  source,
  action_type,
  action_detail,
  user_id = null,
  result = null,
  correlation_id = null,
  notes = null
}) {
  try {
    await db.query(`
      INSERT INTO agent_action_log (
        timestamp, source, action_type, action_detail, user_id, result, correlation_id, notes
      ) VALUES (
        NOW(), $1, $2, $3, $4, $5, $6, $7
      )
    `, [
      source,
      action_type,
      JSON.stringify(action_detail),
      user_id,
      result,
      correlation_id,
      notes
    ]);
  } catch (err) {
    console.error("⚠️ Failed to log agent action:", err);
  }
}

module.exports = { logAgentAction };