import { useEffect, useState } from 'react';
import { fetchRegions } from '../api.js';

export default function useRegions() {
  const [regions, setRegions] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    fetchRegions()
      .then(value => { if (live) setRegions(value); })
      .catch(() => {})
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);
  return { regions, loading };
}
