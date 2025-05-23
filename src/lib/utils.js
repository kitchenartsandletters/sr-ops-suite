const { Pool } = require('pg');
const db = new Pool({ connectionString: process.env.SR_DATABASE_URL });

async function getSystemStatus() {
  try {
    const result = await db.query(
      'SELECT * FROM jobs_status ORDER BY updated_at DESC'
    );

    return {
      jobs: result.rows,
      timestamp: new Date().toISOString()
    };
  } catch (error) {
    console.error("Postgres fetch error:", error);
    return { error: "Could not fetch job status" };
  }
}

async function triggerWorkflow(workflowId) {
  // Placeholder: Use GitHub Actions API or Railway API
  return { success: true, triggered: workflowId };
}

module.exports = { getSystemStatus, triggerWorkflow };
