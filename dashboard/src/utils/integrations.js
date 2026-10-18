const LABELS = {
  agentmail: 'AgentMail', gmail: 'Gmail', fullenrich: 'FullEnrich', apify: 'Apify', firecrawl: 'Firecrawl',
};

export function integrationErrorMessage(error, fallback) {
  if (error?.integration) return `Connect ${LABELS[error.integration] || error.integration} in Settings`;
  return error?.message || fallback;
}
