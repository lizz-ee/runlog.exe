import React, { useEffect, useState, useRef } from 'react';
import TabPanel, { Tab } from '../common/TabPanel';
import { useApp } from '../../contexts/AppContext';

function InstagramLiveTab() {
  const { selectedPost, setSelectedPost, focusPanel } = useApp();
  const postRefs = useRef<{ [key: string]: HTMLDivElement | null }>({});

  const livePosts = [
    { id: 'live-ig1', username: 'your_brand', avatar: 'U', image: true, likes: 1245, comments: 132, shares: 45, caption: 'Summer vibes ☀️ #lifestyle', platform: 'instagram' as const, timestamp: '2 days ago', status: 'published' },
    { id: 'live-ig2', username: 'your_brand', avatar: 'U', image: true, likes: 892, comments: 98, shares: 23, caption: 'New collection drop 🔥', platform: 'instagram' as const, timestamp: '5 days ago', status: 'published' },
    { id: 'live-ig3', username: 'your_brand', avatar: 'U', image: true, likes: 2156, comments: 234, shares: 78, caption: 'Behind the scenes 📸', platform: 'instagram' as const, timestamp: '1 week ago', status: 'published' },
  ];

  // Auto-scroll to selected post
  useEffect(() => {
    if (selectedPost && selectedPost.platform === 'instagram') {
      const selectedPostElement = postRefs.current[selectedPost.caption];
      if (selectedPostElement) {
        // Small delay to ensure the tab has switched and rendered
        setTimeout(() => {
          selectedPostElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
      }
    }
  }, [selectedPost]);

  const handlePostClick = (post: typeof livePosts[0]) => {
    setSelectedPost(post);
    focusPanel('analytics');
  };

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-4 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Instagram Live Feed</h2>
        <p className="text-scian-text-secondary text-sm">Your published Instagram posts</p>
      </div>

      <div className="space-y-6">
        {livePosts.map((post, i) => {
          const isSelected = selectedPost && selectedPost.caption === post.caption;

          return (
            <div
              key={i}
              ref={(el) => (postRefs.current[post.caption] = el)}
              onClick={() => handlePostClick(post)}
              className={`bg-scian-panel border rounded-lg overflow-hidden transition-all animate-fadeIn cursor-pointer hover:scale-[1.02] relative ${
                isSelected
                  ? 'border-scian-cyan shadow-lg shadow-scian-cyan/30 ring-2 ring-scian-cyan/20'
                  : 'border-scian-border hover:border-platform-instagram-mid hover:shadow-lg hover:shadow-platform-instagram-mid/10'
              }`}
              style={{ animationDelay: `${i * 100}ms` }}
            >
            {/* Published Badge */}
            <div className="absolute top-3 right-3 z-10 px-2 py-1 bg-scian-green/20 backdrop-blur-sm rounded text-xs font-medium text-scian-green border border-scian-green/30">
              Published
            </div>

            {/* Post Header */}
            <div className="flex items-center gap-3 p-3 border-b border-scian-border">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-platform-instagram-start via-platform-instagram-mid to-platform-instagram-end flex items-center justify-center text-sm font-semibold text-white ring-2 ring-platform-instagram-mid/20">
                {post.avatar}
              </div>
              <div className="flex-1">
                <span className="text-sm font-medium text-scian-text-primary">{post.username}</span>
                <div className="text-xs text-scian-text-muted">{post.timestamp}</div>
              </div>
            </div>

            {/* Post Image */}
            <div className="aspect-square bg-gradient-to-br from-scian-darker to-scian-panel flex items-center justify-center relative group">
              <div className="text-scian-text-muted text-sm">Published Image</div>
              <div className="absolute inset-0 bg-gradient-to-br from-platform-instagram-start/0 to-platform-instagram-end/5 opacity-0 group-hover:opacity-100 transition-opacity"></div>
            </div>

            {/* Post Actions & Stats */}
            <div className="p-3 space-y-2">
              <div className="flex items-center gap-4 text-scian-text-secondary text-sm">
                <button className="hover:text-platform-instagram-mid transition-colors flex items-center gap-1">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
                  </svg>
                  <span className="font-medium">{post.likes.toLocaleString()}</span>
                </button>
                <button className="hover:text-platform-instagram-mid transition-colors flex items-center gap-1">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                  </svg>
                  <span className="font-medium">{post.comments}</span>
                </button>
                <button className="hover:text-platform-instagram-mid transition-colors flex items-center gap-1">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
                  </svg>
                  <span className="font-medium">{post.shares}</span>
                </button>
              </div>
              <div className="text-sm">
                <span className="font-medium text-scian-text-primary">{post.username}</span>
                <span className="text-scian-text-secondary ml-2">{post.caption}</span>
              </div>
            </div>
          </div>
          );
        })}
      </div>
    </div>
  );
}

function FacebookLiveTab() {
  const livePosts = [
    { name: 'Your Brand', time: '3 days ago', text: 'Exciting news! Check out our latest product launch 🚀', likes: 1456, comments: 189, shares: 215, status: 'published' },
    { name: 'Your Brand', time: '1 week ago', text: 'Thank you for 10,000 followers! 🎉', likes: 2345, comments: 456, shares: 123, status: 'published' },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-4 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Facebook Live Feed</h2>
        <p className="text-scian-text-secondary text-sm">Your published Facebook posts</p>
      </div>

      <div className="space-y-6">
        {livePosts.map((post, i) => (
          <div key={i} className="bg-scian-panel border border-scian-border rounded-lg hover:border-platform-facebook transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-platform-facebook/10 animate-fadeIn relative cursor-pointer" style={{ animationDelay: `${i * 100}ms` }}>
            {/* Published Badge */}
            <div className="absolute top-4 right-4 z-10 px-2 py-1 bg-scian-green/20 backdrop-blur-sm rounded text-xs font-medium text-scian-green border border-scian-green/30">
              Published
            </div>

            {/* Post Header */}
            <div className="p-4">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-10 h-10 rounded-full bg-platform-facebook flex items-center justify-center text-sm font-semibold text-white ring-2 ring-platform-facebook/20">
                  B
                </div>
                <div>
                  <div className="text-sm font-medium text-scian-text-primary">{post.name}</div>
                  <div className="text-xs text-scian-text-secondary">{post.time}</div>
                </div>
              </div>

              <p className="text-scian-text-primary mb-3">{post.text}</p>

              {/* Post Image Placeholder */}
              <div className="aspect-video bg-gradient-to-br from-scian-darker to-scian-panel rounded flex items-center justify-center mb-3 group relative">
                <div className="text-scian-text-muted text-sm">Published Image</div>
                <div className="absolute inset-0 bg-platform-facebook/5 opacity-0 group-hover:opacity-100 transition-opacity rounded"></div>
              </div>

              {/* Engagement Stats */}
              <div className="flex items-center justify-between text-sm text-scian-text-secondary border-t border-scian-border pt-3 mt-3">
                <button className="hover:text-platform-facebook transition-colors font-medium">👍 {post.likes.toLocaleString()}</button>
                <div className="flex gap-4">
                  <span className="font-medium">{post.comments} comments</span>
                  <span className="font-medium">{post.shares} shares</span>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TwitterLiveTab() {
  const liveTweets = [
    { handle: '@your_brand', name: 'Your Brand', time: '2d', text: 'Excited to announce our new partnership! 🎉 #innovation #business', replies: 112, retweets: 445, likes: 1280, status: 'published' },
    { handle: '@your_brand', name: 'Your Brand', time: '5d', text: 'Monday motivation: Stay focused on your goals 💪', replies: 78, retweets: 223, likes: 892, status: 'published' },
    { handle: '@your_brand', name: 'Your Brand', time: '1w', text: 'New blog post is live! Check it out 📝', replies: 45, retweets: 156, likes: 634, status: 'published' },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-4 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Twitter Live Feed</h2>
        <p className="text-scian-text-secondary text-sm">Your published tweets</p>
      </div>

      <div className="space-y-4">
        {liveTweets.map((tweet, i) => (
          <div key={i} className="bg-scian-panel border border-scian-border rounded-lg p-4 hover:bg-scian-hover hover:border-platform-twitter transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-platform-twitter/10 animate-fadeIn relative cursor-pointer" style={{ animationDelay: `${i * 100}ms` }}>
            {/* Published Badge */}
            <div className="absolute top-3 right-3 px-2 py-1 bg-scian-green/20 backdrop-blur-sm rounded text-xs font-medium text-scian-green border border-scian-green/30">
              Published
            </div>

            <div className="flex gap-3">
              <div className="w-10 h-10 rounded-full bg-platform-twitter flex items-center justify-center text-sm font-semibold text-white flex-shrink-0 ring-2 ring-platform-twitter/20">
                B
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-scian-text-primary">{tweet.name}</span>
                  <span className="text-scian-text-secondary text-sm">{tweet.handle}</span>
                  <span className="text-scian-text-muted text-sm">· {tweet.time}</span>
                </div>
                <p className="text-scian-text-primary mb-3">{tweet.text}</p>
                <div className="flex items-center gap-6 text-sm text-scian-text-secondary">
                  <button className="hover:text-platform-twitter transition-colors flex items-center gap-1">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                    <span className="font-medium">{tweet.replies}</span>
                  </button>
                  <button className="hover:text-platform-twitter transition-colors flex items-center gap-1">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    <span className="font-medium">{tweet.retweets}</span>
                  </button>
                  <button className="hover:text-platform-twitter transition-colors flex items-center gap-1">
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
                    </svg>
                    <span className="font-medium">{tweet.likes.toLocaleString()}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TikTokLiveTab() {
  const liveVideos = [
    { username: 'your_brand', views: '1.2M', likes: '125K', comments: 4567, shares: 2345, caption: 'Behind the scenes 🎬 #bts', timestamp: '4 days ago', status: 'published' },
    { username: 'your_brand', views: '856K', likes: '89K', comments: 3421, shares: 1876, caption: 'New product reveal! 🔥', timestamp: '1 week ago', status: 'published' },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-4 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">TikTok Live Feed</h2>
        <p className="text-scian-text-secondary text-sm">Your published TikTok videos</p>
      </div>

      <div className="space-y-6">
        {liveVideos.map((video, i) => (
          <div key={i} className="bg-scian-panel border border-scian-border rounded-lg overflow-hidden hover:border-platform-tiktok-accent transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-platform-tiktok-accent/10 animate-fadeIn relative cursor-pointer" style={{ animationDelay: `${i * 100}ms` }}>
            {/* Published Badge */}
            <div className="absolute top-3 right-3 z-20 px-2 py-1 bg-scian-green/20 backdrop-blur-sm rounded text-xs font-medium text-scian-green border border-scian-green/30">
              Published
            </div>

            {/* Video Placeholder */}
            <div className="aspect-[9/16] bg-gradient-to-br from-platform-tiktok to-scian-darker flex items-center justify-center relative group">
              <div className="text-scian-text-muted text-sm">Published Video</div>
              <div className="absolute inset-0 bg-gradient-to-t from-platform-tiktok via-transparent to-transparent opacity-60"></div>
              <div className="absolute bottom-4 left-4 right-4 z-10">
                <div className="text-white font-medium mb-2">@{video.username}</div>
                <div className="text-white text-sm mb-1">{video.caption}</div>
                <div className="text-white/70 text-xs">{video.timestamp}</div>
              </div>
              <div className="absolute inset-0 bg-platform-tiktok-accent/5 opacity-0 group-hover:opacity-100 transition-opacity"></div>
            </div>

            {/* Video Stats */}
            <div className="p-3 flex items-center justify-around text-sm text-scian-text-secondary bg-scian-darker">
              <div className="text-center">
                <div className="text-scian-text-primary font-medium">{video.views}</div>
                <div className="text-xs">Views</div>
              </div>
              <div className="text-center">
                <div className="text-platform-tiktok-accent font-medium">{video.likes}</div>
                <div className="text-xs">Likes</div>
              </div>
              <div className="text-center">
                <div className="text-scian-text-primary font-medium">{video.comments.toLocaleString()}</div>
                <div className="text-xs">Comments</div>
              </div>
              <div className="text-center">
                <div className="text-scian-text-primary font-medium">{video.shares.toLocaleString()}</div>
                <div className="text-xs">Shares</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function LiveFeed() {
  const { selectedPost } = useApp();
  const [activeTab, setActiveTab] = useState('instagram');

  // Auto-switch to the platform tab when a comment is clicked in Inbox
  useEffect(() => {
    if (selectedPost && selectedPost.platform) {
      setActiveTab(selectedPost.platform);
    }
  }, [selectedPost]);

  const tabs: Tab[] = [
    {
      id: 'instagram',
      label: 'Instagram',
      content: <InstagramLiveTab />,
    },
    {
      id: 'facebook',
      label: 'Facebook',
      content: <FacebookLiveTab />,
    },
    {
      id: 'twitter',
      label: 'Twitter',
      content: <TwitterLiveTab />,
    },
    {
      id: 'tiktok',
      label: 'TikTok',
      content: <TikTokLiveTab />,
    },
  ];

  return <TabPanel tabs={tabs} defaultTab={activeTab} key={activeTab} />;
}
