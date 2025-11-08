import React from 'react';
import TabPanel, { Tab } from '../common/TabPanel';
import { useApp } from '../../contexts/AppContext';

function AllMediaTab() {
  const { setSelectedMedia, focusPanel } = useApp();

  const mediaItems = [
    { id: 'media1', type: 'image' as const, url: '/placeholder-1.jpg', name: 'Summer Photo' },
    { id: 'media2', type: 'image' as const, url: '/placeholder-2.jpg', name: 'Product Shot' },
    { id: 'media3', type: 'video' as const, url: '/placeholder-3.mp4', name: 'Behind the Scenes' },
    { id: 'media4', type: 'image' as const, url: '/placeholder-4.jpg', name: 'Brand Logo' },
    { id: 'media5', type: 'image' as const, url: '/placeholder-5.jpg', name: 'Lifestyle' },
    { id: 'media6', type: 'video' as const, url: '/placeholder-6.mp4', name: 'Tutorial' },
    { id: 'media7', type: 'image' as const, url: '/placeholder-7.jpg', name: 'Event Photo' },
    { id: 'media8', type: 'image' as const, url: '/placeholder-8.jpg', name: 'Team Photo' },
  ];

  const handleMediaClick = (media: typeof mediaItems[0]) => {
    setSelectedMedia(media);
    focusPanel('mediaeditor');
  };

  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">All Media</h2>
        <p className="text-scian-text-secondary text-sm">Your creative assets in one place</p>
      </div>

      <div className="grid grid-cols-4 gap-4">
        {mediaItems.map((media, i) => (
          <div
            key={i}
            onClick={() => handleMediaClick(media)}
            className="aspect-square bg-scian-panel rounded-lg border border-scian-border hover:border-scian-cyan transition-all cursor-pointer flex items-center justify-center group relative hover:scale-105 hover:shadow-lg hover:shadow-scian-cyan/20 animate-fadeIn"
            style={{ animationDelay: `${i * 50}ms` }}
          >
            <svg className="w-12 h-12 text-scian-text-muted group-hover:text-scian-cyan transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            {media.type === 'video' && (
              <div className="absolute top-2 right-2 bg-scian-darker/80 backdrop-blur-sm rounded px-2 py-1 text-xs text-scian-text-primary">
                VIDEO
              </div>
            )}
            <div className="absolute inset-0 bg-gradient-to-t from-scian-darker/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity rounded-lg flex items-end p-2">
              <span className="text-xs text-white font-medium">{media.name}</span>
            </div>
          </div>
        ))}
      </div>

      <button className="mt-6 w-full py-3 bg-gradient-to-r from-scian-cyan to-scian-blue text-white rounded-lg font-medium hover:opacity-90 transition-opacity shadow-lg">
        Upload Media
      </button>
    </div>
  );
}

function ImagesTab() {
  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Images</h2>
        <p className="text-scian-text-secondary text-sm">Photos and graphics</p>
      </div>
      <div className="grid grid-cols-4 gap-4">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="aspect-square bg-scian-panel rounded-lg border border-scian-border hover:border-scian-cyan transition-all hover:scale-105 hover:shadow-lg hover:shadow-scian-cyan/20 cursor-pointer animate-fadeIn" style={{ animationDelay: `${i * 50}ms` }} />
        ))}
      </div>
    </div>
  );
}

function VideosTab() {
  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Videos</h2>
        <p className="text-scian-text-secondary text-sm">Video content</p>
      </div>
      <div className="grid grid-cols-3 gap-4">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="aspect-video bg-scian-panel rounded-lg border border-scian-border hover:border-scian-blue transition-all hover:scale-105 hover:shadow-lg hover:shadow-scian-blue/20 cursor-pointer flex items-center justify-center animate-fadeIn" style={{ animationDelay: `${i * 50}ms` }}>
            <svg className="w-12 h-12 text-scian-text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function MediaGrid() {
  const tabs: Tab[] = [
    {
      id: 'all',
      label: 'All',
      content: <AllMediaTab />,
    },
    {
      id: 'images',
      label: 'Images',
      content: <ImagesTab />,
    },
    {
      id: 'videos',
      label: 'Videos',
      content: <VideosTab />,
    },
  ];

  return <TabPanel tabs={tabs} defaultTab="all" />;
}
