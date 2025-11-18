import { useRef, useState, useEffect } from 'react';
import type { Version, AnnotationData } from '../lib/types';

interface VideoPlayerProps {
  version: Version;
  onComment: (frame: number, annotation?: AnnotationData) => void;
}

export default function VideoPlayer({ version, onComment }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [currentFrame, setCurrentFrame] = useState(0);

  const fps = version.fps || 24;

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.load();
    }
  }, [version.file_path]);

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime);
      setCurrentFrame(Math.floor(videoRef.current.currentTime * fps));
    }
  };

  const handleLoadedMetadata = () => {
    if (videoRef.current) {
      setDuration(videoRef.current.duration);
    }
  };

  const togglePlay = () => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
      } else {
        videoRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value);
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      setCurrentTime(time);
    }
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="h-full flex flex-col bg-black">
      {/* Video Container */}
      <div className="flex-1 flex items-center justify-center relative">
        <video
          ref={videoRef}
          className="max-w-full max-h-full"
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetadata={handleLoadedMetadata}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
        >
          <source src={`file://${version.file_path}`} type={version.mime_type || 'video/mp4'} />
          Your browser does not support the video tag.
        </video>

        {/* File path warning overlay */}
        <div className="absolute bottom-4 right-4 bg-black/80 px-4 py-2 rounded text-xs text-gray-400 max-w-md">
          <div className="font-mono truncate">{version.file_path}</div>
          <div className="text-yellow-400 mt-1">
            Note: File path playback requires Electron file:// protocol support
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="bg-gray-900 px-6 py-4 border-t border-gray-700">
        {/* Timeline */}
        <input
          type="range"
          min="0"
          max={duration || 0}
          value={currentTime}
          onChange={handleSeek}
          step="0.01"
          className="w-full mb-4 h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
        />

        {/* Controls Row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <button
              onClick={togglePlay}
              className="w-10 h-10 flex items-center justify-center bg-blue-600 hover:bg-blue-700 rounded-full transition-colors"
            >
              {isPlaying ? '⏸' : '▶'}
            </button>
            <div className="text-sm text-gray-400">
              {formatTime(currentTime)} / {formatTime(duration)}
            </div>
            <div className="text-sm text-gray-500">
              Frame: {currentFrame}
            </div>
          </div>

          <button
            onClick={() => onComment(currentFrame)}
            className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg text-sm transition-colors"
          >
            + Add Comment
          </button>
        </div>
      </div>
    </div>
  );
}
