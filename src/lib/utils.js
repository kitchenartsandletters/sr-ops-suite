const { createClient } = require("@supabase/supabase-js");

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

async function getSystemStatus() {
  const { data: jobs, error } = await supabase
    .from("jobs_status")
    .select("*")
    .order("updated_at", { ascending: false });

  if (error) {
    console.error("Supabase fetch error:", error);
    return { error: "Could not fetch job status" };
  }

  return {
    jobs,
    timestamp: new Date().toISOString()
  };
}

async function triggerWorkflow(workflowId) {
  // Placeholder: Use GitHub Actions API or Railway API
  return { success: true, triggered: workflowId };
}

module.exports = { getSystemStatus, triggerWorkflow };
