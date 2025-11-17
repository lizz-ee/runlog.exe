import { useState, useEffect } from 'react';
import type { Project, Shot, Sequence } from '../lib/types';
import { shotsApi, sequencesApi } from '../lib/api';
import { STATUS_LABELS, STATUS_COLORS, PRIORITY_COLORS } from '../lib/types';

interface ProjectViewProps {
  project: Project;
  onShotSelect: (shot: Shot) => void;
}

export default function ProjectView({ project, onShotSelect }: ProjectViewProps) {
  const [shots, setShots] = useState<Shot[]>([]);
  const [sequences, setSequences] = useState<Sequence[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newShot, setNewShot] = useState({
    name: '',
    code: '',
    sequence_id: 0,
    frame_start: 1,
    frame_end: 100,
    fps: 24
  });

  useEffect(() => {
    loadData();
  }, [project.id]);

  const loadData = async () => {
    setLoading(true);
    try {
      const [shotsRes, seqsRes] = await Promise.all([
        shotsApi.listByProject(project.id),
        sequencesApi.list(project.id)
      ]);
      setShots(shotsRes.data);
      setSequences(seqsRes.data);

      // Create default sequence if none exists
      if (seqsRes.data.length === 0) {
        const newSeq = await sequencesApi.create({
          project_id: project.id,
          name: 'Sequence 01',
          code: 'SEQ01',
          description: 'Default sequence'
        });
        setSequences([newSeq.data]);
        setNewShot({ ...newShot, sequence_id: newSeq.data.id });
      } else {
        setNewShot({ ...newShot, sequence_id: seqsRes.data[0].id });
      }
    } catch (error) {
      console.error('Failed to load project data:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateShot = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await shotsApi.create({
        sequence_id: newShot.sequence_id,
        name: newShot.name,
        code: newShot.code.toUpperCase(),
        frame_start: newShot.frame_start,
        frame_end: newShot.frame_end,
        fps: newShot.fps,
        status: 'wtg',
        priority: 'medium'
      });
      setShowCreateModal(false);
      setNewShot({ name: '', code: '', sequence_id: sequences[0]?.id || 0, frame_start: 1, frame_end: 100, fps: 24 });
      loadData();
    } catch (error) {
      console.error('Failed to create shot:', error);
      alert('Failed to create shot');
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center h-full">Loading...</div>;
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-8 py-6 border-b border-gray-700">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-3xl font-bold">{project.name}</h2>
            <p className="text-gray-400 mt-1">
              {shots.length} {shots.length === 1 ? 'shot' : 'shots'}
            </p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors"
          >
            + New Shot
          </button>
        </div>
      </div>

      {/* Shots Grid */}
      <div className="flex-1 overflow-auto p-8">
        {shots.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-500">
            <div className="text-center">
              <div className="text-6xl mb-4">🎬</div>
              <p className="text-xl">No shots yet</p>
              <p className="text-sm mt-2">Create your first shot to get started</p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
            {shots.map((shot) => (
              <button
                key={shot.id}
                onClick={() => onShotSelect(shot)}
                className="bg-gray-800 rounded-lg p-6 hover:bg-gray-750 border border-gray-700 hover:border-blue-500 transition-all text-left group"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <h3 className="text-lg font-bold group-hover:text-blue-400 transition-colors">
                      {shot.name}
                    </h3>
                    <p className="text-xs text-gray-500 mt-1">{shot.code}</p>
                  </div>
                  <div className="flex flex-col gap-1">
                    <div
                      className="px-2 py-1 rounded text-xs font-medium text-center"
                      style={{ backgroundColor: STATUS_COLORS[shot.status] + '20', color: STATUS_COLORS[shot.status] }}
                    >
                      {STATUS_LABELS[shot.status]}
                    </div>
                    <div
                      className="px-2 py-1 rounded text-xs font-medium text-center"
                      style={{ backgroundColor: PRIORITY_COLORS[shot.priority] + '20', color: PRIORITY_COLORS[shot.priority] }}
                    >
                      {shot.priority.toUpperCase()}
                    </div>
                  </div>
                </div>
                {shot.description && (
                  <p className="text-sm text-gray-400 line-clamp-2 mb-3">{shot.description}</p>
                )}
                <div className="pt-3 border-t border-gray-700 text-xs text-gray-500">
                  {shot.frame_start && shot.frame_end ? (
                    <div>Frames: {shot.frame_start}-{shot.frame_end} ({shot.frame_duration || (shot.frame_end - shot.frame_start + 1)})</div>
                  ) : (
                    <div>No frame range set</div>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Create Shot Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-8 max-w-md w-full mx-4">
            <h3 className="text-2xl font-bold mb-6">Create New Shot</h3>
            <form onSubmit={handleCreateShot}>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2">Shot Name</label>
                  <input
                    type="text"
                    value={newShot.name}
                    onChange={(e) => setNewShot({ ...newShot, name: e.target.value })}
                    className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="Hero Shot 010"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-2">Shot Code</label>
                  <input
                    type="text"
                    value={newShot.code}
                    onChange={(e) => setNewShot({ ...newShot, code: e.target.value })}
                    className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 uppercase"
                    placeholder="SH010"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-2">Sequence</label>
                  <select
                    value={newShot.sequence_id}
                    onChange={(e) => setNewShot({ ...newShot, sequence_id: parseInt(e.target.value) })}
                    className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    required
                  >
                    {sequences.map((seq) => (
                      <option key={seq.id} value={seq.id}>{seq.name} ({seq.code})</option>
                    ))}
                  </select>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2">Frame Start</label>
                    <input
                      type="number"
                      value={newShot.frame_start}
                      onChange={(e) => setNewShot({ ...newShot, frame_start: parseInt(e.target.value) })}
                      className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2">Frame End</label>
                    <input
                      type="number"
                      value={newShot.frame_end}
                      onChange={(e) => setNewShot({ ...newShot, frame_end: parseInt(e.target.value) })}
                      className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                </div>
              </div>
              <div className="flex space-x-3 mt-8">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
                >
                  Create Shot
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
