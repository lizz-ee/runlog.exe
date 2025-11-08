import React, { useState, useEffect } from 'react';
import TabPanel, { Tab } from '../common/TabPanel';
import { useApp } from '../../contexts/AppContext';

function CreatePostTab() {
  const { selectedPost, currentDraft, setCurrentDraft } = useApp();
  const [caption, setCaption] = useState('');
  const [selectedPlatform, setSelectedPlatform] = useState<'Instagram' | 'Facebook' | 'TikTok' | 'Twitter'>('Instagram');

  // Auto-populate when a DRAFT post is selected from Feed Preview
  // Don't populate for published posts (from LiveFeed/Inbox)
  useEffect(() => {
    if (selectedPost && selectedPost.status !== 'published') {
      setCaption(selectedPost.caption);
      setSelectedPlatform(selectedPost.platform.charAt(0).toUpperCase() + selectedPost.platform.slice(1) as 'Instagram' | 'Facebook' | 'TikTok' | 'Twitter');
    }
  }, [selectedPost]);

  // Auto-populate from AI template or other draft sources
  useEffect(() => {
    if (currentDraft && currentDraft.caption !== caption) {
      setCaption(currentDraft.caption);
      setSelectedPlatform(currentDraft.platform.charAt(0).toUpperCase() + currentDraft.platform.slice(1) as 'Instagram' | 'Facebook' | 'TikTok' | 'Twitter');
    }
  }, [currentDraft]);

  // Update draft in context for live preview
  useEffect(() => {
    if (caption || selectedPlatform) {
      setCurrentDraft({
        caption,
        platform: selectedPlatform.toLowerCase() as 'instagram' | 'facebook' | 'tiktok' | 'twitter'
      });
    }
  }, [caption, selectedPlatform, setCurrentDraft]);

  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Create Post</h2>
        <p className="text-scian-text-secondary text-sm">AI-powered content creation</p>
      </div>

      {/* Platform selector */}
      <div className="mb-4">
        <label className="text-sm text-scian-text-secondary mb-2 block">Platforms</label>
        <div className="flex gap-2">
          {(['Instagram', 'Facebook', 'TikTok', 'Twitter'] as const).map((platform) => (
            <button
              key={platform}
              onClick={() => setSelectedPlatform(platform)}
              className={`px-4 py-2 rounded-lg text-sm transition-all border ${
                selectedPlatform === platform
                  ? 'bg-scian-cyan text-white border-scian-cyan shadow-lg shadow-scian-cyan/20'
                  : 'bg-scian-panel text-scian-text-primary hover:bg-scian-hover border-scian-border'
              }`}
            >
              {platform}
            </button>
          ))}
        </div>
      </div>

      {/* Caption editor */}
      <div className="mb-4">
        <label className="text-sm text-scian-text-secondary mb-2 block">Caption</label>
        <textarea
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
          placeholder="Write your caption or let AI generate one..."
          className="w-full h-32 bg-scian-darker border border-scian-border rounded-lg p-3 text-scian-text-primary placeholder-scian-text-muted focus:border-scian-cyan focus:outline-none resize-none"
        />
      </div>

      {/* AI Actions - KEEPING THE BEAUTIFUL GRADIENTS! */}
      <div className="flex gap-2 mb-4">
        <button className="flex-1 py-2 bg-scian-violet rounded-lg text-sm font-medium text-white hover:opacity-90 transition-opacity shadow-lg">
          ✨ Generate Caption
        </button>
        <button className="flex-1 py-2 bg-scian-blue rounded-lg text-sm font-medium text-white hover:opacity-90 transition-opacity shadow-lg">
          🏷️ Suggest Tags
        </button>
      </div>

      {/* Schedule/Post */}
      <div className="flex gap-2">
        <button className="flex-1 py-3 bg-scian-panel rounded-lg font-medium text-scian-text-primary hover:bg-scian-hover transition-colors border border-scian-border">
          Schedule
        </button>
        <button className="flex-1 py-3 bg-gradient-to-r from-scian-peach to-scian-violet rounded-lg font-medium text-white hover:opacity-90 transition-opacity shadow-lg">
          Post Now
        </button>
      </div>
    </div>
  );
}

function DraftsTab() {
  const drafts = [
    { id: 1, caption: 'Summer vibes... ☀️', platform: 'Instagram', date: '2 hours ago' },
    { id: 2, caption: 'New product launch!', platform: 'Facebook', date: '1 day ago' },
    { id: 3, caption: 'Behind the scenes', platform: 'TikTok', date: '3 days ago' },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Drafts</h2>
        <p className="text-scian-text-secondary text-sm">Your saved posts</p>
      </div>

      <div className="space-y-3">
        {drafts.map((draft, i) => (
          <div
            key={draft.id}
            className="bg-scian-panel border border-scian-border rounded-lg p-4 hover:border-scian-cyan transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-scian-cyan/20 cursor-pointer animate-fadeIn"
            style={{ animationDelay: `${i * 100}ms` }}
          >
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs text-scian-text-secondary">{draft.platform}</span>
              <span className="text-xs text-scian-text-muted">{draft.date}</span>
            </div>
            <p className="text-scian-text-primary">{draft.caption}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function ScheduledTab() {
  const scheduled = [
    { id: 1, caption: 'Monday motivation', platform: 'Instagram', date: 'Mon, 10:00 AM' },
    { id: 2, caption: 'Product feature highlight', platform: 'Facebook', date: 'Tue, 2:00 PM' },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Scheduled Posts</h2>
        <p className="text-scian-text-secondary text-sm">Upcoming content</p>
      </div>

      <div className="space-y-3">
        {scheduled.map((post, i) => (
          <div
            key={post.id}
            className="bg-scian-panel border border-scian-border rounded-lg p-4 hover:border-scian-blue transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-scian-blue/20 cursor-pointer animate-fadeIn"
            style={{ animationDelay: `${i * 100}ms` }}
          >
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs text-scian-text-secondary">{post.platform}</span>
              <span className="text-xs font-medium text-scian-cyan">{post.date}</span>
            </div>
            <p className="text-scian-text-primary">{post.caption}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function PostEditor() {
  const tabs: Tab[] = [
    {
      id: 'create',
      label: 'Create',
      content: <CreatePostTab />,
    },
    {
      id: 'drafts',
      label: 'Drafts',
      content: <DraftsTab />,
    },
    {
      id: 'scheduled',
      label: 'Scheduled',
      content: <ScheduledTab />,
    },
  ];

  return <TabPanel tabs={tabs} defaultTab="create" />;
}
