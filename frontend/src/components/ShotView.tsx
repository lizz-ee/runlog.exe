import { useState, useEffect } from 'react';
import type { Shot, Version, Comment, User } from '../lib/types';
import { versionsApi, commentsApi, usersApi } from '../lib/api';
import VideoPlayer from './VideoPlayer';
import CommentsList from './CommentsList';

interface ShotViewProps {
  shot: Shot;
}

export default function ShotView({ shot }: ShotViewProps) {
  const [versions, setVersions] = useState<Version[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<Version | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddVersion, setShowAddVersion] = useState(false);
  const [newVersionPath, setNewVersionPath] = useState('');

  useEffect(() => {
    loadData();
  }, [shot.id]);

  useEffect(() => {
    if (selectedVersion) {
      loadComments();
    }
  }, [selectedVersion]);

  const loadData = async () => {
    setLoading(true);
    try {
      const [versionsRes, usersRes] = await Promise.all([
        versionsApi.listByShot(shot.id),
        usersApi.list()
      ]);
      setVersions(versionsRes.data);
      setUsers(usersRes.data);
      if (versionsRes.data.length > 0) {
        setSelectedVersion(versionsRes.data[0]);
      }
    } catch (error) {
      console.error('Failed to load shot data:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadComments = async () => {
    if (!selectedVersion) return;
    try {
      const res = await commentsApi.list(selectedVersion.id);
      setComments(res.data);
    } catch (error) {
      console.error('Failed to load comments:', error);
    }
  };

  const handleAddVersion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!users.length) {
      alert('No users found. Please create a user first.');
      return;
    }

    try {
      const fileName = newVersionPath.split('/').pop() || 'version';
      const versionNumber = versions.length + 1;

      await versionsApi.create({
        name: `${shot.name} v${versionNumber}`,
        version_number: versionNumber,
        file_path: newVersionPath,
        file_name: fileName,
        shot_id: shot.id,
        uploaded_by_id: users[0].id,
        fps: shot.fps
      });

      setShowAddVersion(false);
      setNewVersionPath('');
      loadData();
    } catch (error: any) {
      console.error('Failed to add version:', error);
      alert(error.response?.data?.detail || 'Failed to add version');
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center h-full">Loading...</div>;
  }

  return (
    <div className="h-full flex flex-col bg-gray-900">
      {/* Shot Header */}
      <div className="px-8 py-4 border-b border-gray-700">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">{shot.name}</h2>
            <p className="text-sm text-gray-400">{shot.code}</p>
          </div>
          <button
            onClick={() => setShowAddVersion(true)}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm transition-colors"
          >
            + Add Version
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Video Player + Comments */}
        <div className="flex-1 flex flex-col border-r border-gray-700">
          {/* Video Player */}
          <div className="flex-1 bg-black">
            {selectedVersion ? (
              <VideoPlayer
                version={selectedVersion}
                onComment={(frame, annotation) => {
                  // Handle adding comment
                  console.log('Add comment at frame:', frame, annotation);
                }}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-gray-500">
                <div className="text-center">
                  <div className="text-6xl mb-4">🎥</div>
                  <p className="text-xl">No versions yet</p>
                  <p className="text-sm mt-2">Add a version to start reviewing</p>
                </div>
              </div>
            )}
          </div>

          {/* Comments Section */}
          {selectedVersion && (
            <div className="h-64 border-t border-gray-700 overflow-auto bg-gray-800 p-4">
              <h3 className="font-bold mb-3">Comments ({comments.length})</h3>
              <CommentsList
                comments={comments}
                users={users}
                onRefresh={loadComments}
              />
            </div>
          )}
        </div>

        {/* Right: Versions List */}
        <div className="w-80 bg-gray-800 overflow-auto">
          <div className="p-4">
            <h3 className="font-bold text-lg mb-4">Versions ({versions.length})</h3>
            <div className="space-y-2">
              {versions.map((version) => (
                <button
                  key={version.id}
                  onClick={() => setSelectedVersion(version)}
                  className={`w-full p-4 rounded-lg text-left transition-colors ${
                    selectedVersion?.id === version.id
                      ? 'bg-blue-600'
                      : 'bg-gray-700 hover:bg-gray-600'
                  }`}
                >
                  <div className="font-medium">{version.name}</div>
                  <div className="text-xs text-gray-400 mt-1">
                    v{version.version_number}
                  </div>
                  <div className="text-xs text-gray-400 mt-1">
                    {new Date(version.uploaded_at).toLocaleString()}
                  </div>
                  {version.duration && (
                    <div className="text-xs text-gray-500 mt-1">
                      {version.duration}s @ {version.fps}fps
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Add Version Modal */}
      {showAddVersion && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-8 max-w-lg w-full mx-4">
            <h3 className="text-2xl font-bold mb-6">Add New Version</h3>
            <form onSubmit={handleAddVersion}>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2">
                    File Path (on network storage)
                  </label>
                  <input
                    type="text"
                    value={newVersionPath}
                    onChange={(e) => setNewVersionPath(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm"
                    placeholder="/mnt/projects/show/shots/SH010/renders/SH010_v003.mp4"
                    required
                  />
                  <p className="text-xs text-gray-500 mt-2">
                    Enter the path to the rendered file on your network storage
                  </p>
                </div>
              </div>
              <div className="flex space-x-3 mt-8">
                <button
                  type="button"
                  onClick={() => {
                    setShowAddVersion(false);
                    setNewVersionPath('');
                  }}
                  className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
                >
                  Add Version
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
