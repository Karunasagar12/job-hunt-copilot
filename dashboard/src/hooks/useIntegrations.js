import { useCallback, useEffect, useState } from 'react';
import { fetchIntegrations } from '../api.js';

export default function useIntegrations() {
  const [list, setList] = useState([]);
  const reload = useCallback(() => fetchIntegrations().then(setList).catch(() => setList([])), []);
  useEffect(() => { reload(); }, [reload]);
  const byId = Object.fromEntries(list.map(integration => [integration.id, integration]));
  return { byId, isConnected: id => byId[id]?.state === 'connected', reload };
}
