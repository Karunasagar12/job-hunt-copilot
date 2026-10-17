import GeoBreakdown from '../components/GeoBreakdown.jsx';
import PipelineFunnel from '../components/PipelineFunnel.jsx';

export default function Analytics() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-950">Analytics</h1>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <PipelineFunnel />
        <GeoBreakdown />
      </div>
    </div>
  );
}
