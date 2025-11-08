import React, { useState, useEffect } from 'react';
import TabPanel, { Tab } from '../common/TabPanel';
import { useApp } from '../../contexts/AppContext';

function InstagramTab() {
  const { setSelectedPost, focusPanel, currentDraft } = useApp();

  const posts = [
    { id: 'ig1', username: 'your_brand', avatar: 'U', image: true, likes: 245, comments: 32, caption: 'Summer vibes ☀️ #lifestyle', platform: 'instagram' as const },
    { id: 'ig2', username: 'your_brand', avatar: 'U', image: true, likes: 189, comments: 28, caption: 'New collection drop 🔥', platform: 'instagram' as const },
  ];

  const handlePostClick = (post: typeof posts[0]) => {
    setSelectedPost(post);
    focusPanel('editor');
  };

  const showLivePreview = currentDraft && currentDraft.platform === 'instagram' && currentDraft.caption;

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-4 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Instagram Feed</h2>
        <p className="text-scian-text-secondary text-sm">Preview your Instagram posts</p>
      </div>

      {/* Live Preview */}
      {showLivePreview && (
        <div className="mb-6 animate-fadeIn">
          <div className="flex items-center gap-2 mb-3">
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-scian-cyan to-transparent"></div>
            <span className="text-xs font-medium text-scian-cyan uppercase tracking-wider px-3 py-1 bg-scian-cyan/10 rounded-full border border-scian-cyan/30">Live Preview</span>
            <div className="h-px flex-1 bg-gradient-to-r from-scian-cyan via-transparent to-transparent"></div>
          </div>

          <div className="bg-gradient-to-br from-scian-panel to-scian-darker border-2 border-scian-cyan rounded-lg overflow-hidden shadow-xl shadow-scian-cyan/20 animate-pulse-slow">
            {/* Post Header */}
            <div className="flex items-center gap-3 p-3 border-b border-scian-cyan/20">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-platform-instagram-start via-platform-instagram-mid to-platform-instagram-end flex items-center justify-center text-sm font-semibold text-white ring-2 ring-platform-instagram-mid/20">
                U
              </div>
              <span className="text-sm font-medium text-scian-text-primary">your_brand</span>
            </div>

            {/* Post Image Placeholder */}
            <div className="aspect-square bg-gradient-to-br from-scian-darker to-scian-panel flex items-center justify-center">
              <div className="text-scian-text-muted text-sm">Live Preview</div>
            </div>

            {/* Post Actions & Caption */}
            <div className="p-3 space-y-2">
              <div className="flex items-center gap-4 text-scian-text-secondary text-sm">
                <div className="flex items-center gap-1">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />
                  </svg>
                </div>
                <div className="flex items-center gap-1">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                  </svg>
                </div>
                <div className="flex items-center gap-1">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
                  </svg>
                </div>
              </div>
              <div className="text-sm">
                <span className="font-medium text-scian-text-primary">your_brand</span>
                <span className="text-scian-text-secondary ml-2">{currentDraft.caption}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-6">
        {posts.map((post, i) => (
          <div
            key={i}
            onClick={() => handlePostClick(post)}
            className="bg-scian-panel border border-scian-border rounded-lg overflow-hidden hover:border-platform-instagram-mid transition-all hover:shadow-lg hover:shadow-platform-instagram-mid/10 animate-fadeIn cursor-pointer hover:scale-[1.02]"
            style={{ animationDelay: `${i * 100}ms` }}
          >
            {/* Post Header */}
            <div className="flex items-center gap-3 p-3 border-b border-scian-border">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-platform-instagram-start via-platform-instagram-mid to-platform-instagram-end flex items-center justify-center text-sm font-semibold text-white ring-2 ring-platform-instagram-mid/20">
                {post.avatar}
              </div>
              <span className="text-sm font-medium text-scian-text-primary">{post.username}</span>
              <div className="ml-auto">
                <div className="w-1 h-1 rounded-full bg-platform-instagram-mid animate-pulse"></div>
              </div>
            </div>

            {/* Post Image */}
            <div className="aspect-square bg-gradient-to-br from-scian-darker to-scian-panel flex items-center justify-center relative group">
              <div className="text-scian-text-muted text-sm">Post Image</div>
              <div className="absolute inset-0 bg-gradient-to-br from-platform-instagram-start/0 to-platform-instagram-end/5 opacity-0 group-hover:opacity-100 transition-opacity"></div>
            </div>

            {/* Post Actions */}
            <div className="p-3 space-y-2">
              <div className="flex items-center gap-4 text-scian-text-secondary text-sm">
                <button className="hover:text-platform-instagram-mid transition-colors flex items-center gap-1">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
                  </svg>
                  <span>{post.likes}</span>
                </button>
                <button className="hover:text-platform-instagram-mid transition-colors flex items-center gap-1">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                  </svg>
                  <span>{post.comments}</span>
                </button>
              </div>
              <div className="text-sm">
                <span className="font-medium text-scian-text-primary">{post.username}</span>
                <span className="text-scian-text-secondary ml-2">{post.caption}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FacebookTab() {
  const { currentDraft } = useApp();

  const posts = [
    { name: 'Your Brand', time: '2 hours ago', text: 'Exciting news! Check out our latest product launch 🚀', likes: 156, comments: 19, shares: 15 },
  ];

  const showLivePreview = currentDraft && currentDraft.platform === 'facebook' && currentDraft.caption;

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-4 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Facebook Feed</h2>
        <p className="text-scian-text-secondary text-sm">Preview your Facebook posts</p>
      </div>

      {/* Live Preview */}
      {showLivePreview && (
        <div className="mb-6 animate-fadeIn">
          <div className="flex items-center gap-2 mb-3">
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-scian-cyan to-transparent"></div>
            <span className="text-xs font-medium text-scian-cyan uppercase tracking-wider px-3 py-1 bg-scian-cyan/10 rounded-full border border-scian-cyan/30">Live Preview</span>
            <div className="h-px flex-1 bg-gradient-to-r from-scian-cyan via-transparent to-transparent"></div>
          </div>

          <div className="bg-gradient-to-br from-scian-panel to-scian-darker border-2 border-scian-cyan rounded-lg overflow-hidden shadow-xl shadow-scian-cyan/20 animate-pulse-slow">
            <div className="p-4">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-10 h-10 rounded-full bg-platform-facebook flex items-center justify-center text-sm font-semibold text-white ring-2 ring-platform-facebook/20">
                  B
                </div>
                <div>
                  <div className="text-sm font-medium text-scian-text-primary">Your Brand</div>
                  <div className="text-xs text-scian-text-secondary">Just now · 🌍</div>
                </div>
              </div>

              <p className="text-scian-text-primary mb-3">{currentDraft.caption}</p>

              <div className="aspect-video bg-gradient-to-br from-scian-darker to-scian-panel rounded flex items-center justify-center mb-3">
                <div className="text-scian-text-muted text-sm">Live Preview</div>
              </div>

              <div className="flex items-center justify-between text-xs text-scian-text-secondary border-t border-scian-cyan/20 pt-3">
                <button className="hover:text-platform-facebook transition-colors">👍 Like</button>
                <div className="flex gap-3">
                  <span>💬 Comment</span>
                  <span>↗️ Share</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-6">
        {posts.map((post, i) => (
          <div key={i} className="bg-scian-panel border border-scian-border rounded-lg hover:border-platform-facebook transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-platform-facebook/10 animate-fadeIn cursor-pointer" style={{ animationDelay: `${i * 100}ms` }}>
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
                <div className="text-scian-text-muted text-sm">Post Image</div>
                <div className="absolute inset-0 bg-platform-facebook/5 opacity-0 group-hover:opacity-100 transition-opacity rounded"></div>
              </div>

              {/* Engagement Stats */}
              <div className="flex items-center justify-between text-xs text-scian-text-secondary border-t border-scian-border pt-3 mt-3">
                <button className="hover:text-platform-facebook transition-colors">👍 {post.likes}</button>
                <div className="flex gap-3">
                  <span>{post.comments} comments</span>
                  <span>{post.shares} shares</span>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TwitterTab() {
  const { currentDraft } = useApp();
  const showLivePreview = currentDraft && currentDraft.platform === 'twitter' && currentDraft.caption;

  const tweets = [
    { handle: '@your_brand', name: 'Your Brand', time: '3h', text: 'Excited to announce our new partnership! 🎉 #innovation #business', replies: 12, retweets: 45, likes: 128 },
    { handle: '@your_brand', name: 'Your Brand', time: '1d', text: 'Monday motivation: Stay focused on your goals 💪', replies: 8, retweets: 23, likes: 89 },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-4 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Twitter Feed</h2>
        <p className="text-scian-text-secondary text-sm">Preview your tweets</p>
      </div>

      {showLivePreview && (
        <div className="mb-6 animate-fadeIn">
          <div className="flex items-center gap-2 mb-3">
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-scian-cyan to-transparent"></div>
            <span className="text-xs font-medium text-scian-cyan uppercase tracking-wider px-3 py-1 bg-scian-cyan/10 rounded-full border border-scian-cyan/30">Live Preview</span>
            <div className="h-px flex-1 bg-gradient-to-r from-scian-cyan via-transparent to-transparent"></div>
          </div>

          <div className="bg-gradient-to-br from-scian-panel to-scian-darker border-2 border-scian-cyan rounded-lg p-4 shadow-xl shadow-scian-cyan/20 animate-pulse-slow">
            <div className="flex gap-3">
              <div className="w-10 h-10 rounded-full bg-platform-twitter flex items-center justify-center text-sm font-semibold text-white flex-shrink-0 ring-2 ring-scian-cyan">
                B
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-scian-text-primary">Your Brand</span>
                  <span className="text-scian-text-secondary text-sm">@your_brand</span>
                  <span className="text-scian-text-muted text-sm">· now</span>
                </div>
                <p className="text-scian-text-primary mb-3 whitespace-pre-wrap">{currentDraft.caption}</p>
                <div className="flex items-center gap-6 text-sm text-scian-text-secondary">
                  <button className="hover:text-platform-twitter transition-colors flex items-center gap-1">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                    <span>0</span>
                  </button>
                  <button className="hover:text-platform-twitter transition-colors flex items-center gap-1">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    <span>0</span>
                  </button>
                  <button className="hover:text-platform-twitter transition-colors flex items-center gap-1">
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
                    </svg>
                    <span>0</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-4">
        {tweets.map((tweet, i) => (
          <div key={i} className="bg-scian-panel border border-scian-border rounded-lg p-4 hover:bg-scian-hover hover:border-platform-twitter transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-platform-twitter/10 animate-fadeIn cursor-pointer" style={{ animationDelay: `${i * 100}ms` }}>
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
                    <span>{tweet.replies}</span>
                  </button>
                  <button className="hover:text-platform-twitter transition-colors flex items-center gap-1">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    <span>{tweet.retweets}</span>
                  </button>
                  <button className="hover:text-platform-twitter transition-colors flex items-center gap-1">
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
                    </svg>
                    <span>{tweet.likes}</span>
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

function TikTokTab() {
  const { currentDraft } = useApp();
  const showLivePreview = currentDraft && currentDraft.platform === 'tiktok' && currentDraft.caption;

  const videos = [
    { username: 'your_brand', views: '125K', likes: '12.5K', comments: 456, shares: 234, caption: 'Behind the scenes 🎬 #bts' },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-4 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">TikTok Feed</h2>
        <p className="text-scian-text-secondary text-sm">Preview your TikTok videos</p>
      </div>

      {showLivePreview && (
        <div className="mb-6 animate-fadeIn">
          <div className="flex items-center gap-2 mb-3">
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-scian-cyan to-transparent"></div>
            <span className="text-xs font-medium text-scian-cyan uppercase tracking-wider px-3 py-1 bg-scian-cyan/10 rounded-full border border-scian-cyan/30">Live Preview</span>
            <div className="h-px flex-1 bg-gradient-to-r from-scian-cyan via-transparent to-transparent"></div>
          </div>

          <div className="bg-gradient-to-br from-scian-panel to-scian-darker border-2 border-scian-cyan rounded-lg overflow-hidden shadow-xl shadow-scian-cyan/20 animate-pulse-slow">
            {/* Video Placeholder */}
            <div className="aspect-[9/16] bg-gradient-to-br from-platform-tiktok to-scian-darker flex items-center justify-center relative">
              <div className="text-scian-text-muted text-sm">Video Preview</div>
              <div className="absolute inset-0 bg-gradient-to-t from-platform-tiktok via-transparent to-transparent opacity-60"></div>
              <div className="absolute bottom-4 left-4 right-4 z-10">
                <div className="text-white font-medium mb-2">@your_brand</div>
                <div className="text-white text-sm whitespace-pre-wrap">{currentDraft.caption}</div>
              </div>
              <div className="absolute inset-0 ring-2 ring-inset ring-scian-cyan/50"></div>
            </div>

            {/* Video Stats */}
            <div className="p-3 flex items-center justify-around text-sm text-scian-text-secondary bg-scian-darker border-t-2 border-scian-cyan">
              <div className="text-center">
                <div className="text-scian-text-primary font-medium">0</div>
                <div className="text-xs">Views</div>
              </div>
              <div className="text-center">
                <div className="text-platform-tiktok-accent font-medium">0</div>
                <div className="text-xs">Likes</div>
              </div>
              <div className="text-center">
                <div className="text-scian-text-primary font-medium">0</div>
                <div className="text-xs">Comments</div>
              </div>
              <div className="text-center">
                <div className="text-scian-text-primary font-medium">0</div>
                <div className="text-xs">Shares</div>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-6">
        {videos.map((video, i) => (
          <div key={i} className="bg-scian-panel border border-scian-border rounded-lg overflow-hidden hover:border-platform-tiktok-accent transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-platform-tiktok-accent/10 animate-fadeIn cursor-pointer" style={{ animationDelay: `${i * 100}ms` }}>
            {/* Video Placeholder */}
            <div className="aspect-[9/16] bg-gradient-to-br from-platform-tiktok to-scian-darker flex items-center justify-center relative group">
              <div className="text-scian-text-muted text-sm">Video Preview</div>
              <div className="absolute inset-0 bg-gradient-to-t from-platform-tiktok via-transparent to-transparent opacity-60"></div>
              <div className="absolute bottom-4 left-4 right-4 z-10">
                <div className="text-white font-medium mb-2">@{video.username}</div>
                <div className="text-white text-sm">{video.caption}</div>
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
                <div className="text-scian-text-primary font-medium">{video.comments}</div>
                <div className="text-xs">Comments</div>
              </div>
              <div className="text-center">
                <div className="text-scian-text-primary font-medium">{video.shares}</div>
                <div className="text-xs">Shares</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function FeedPreview() {
  const { currentDraft } = useApp();
  const [activeTab, setActiveTab] = useState('instagram');

  // Auto-switch to the platform tab when platform is changed in Post Editor
  useEffect(() => {
    if (currentDraft && currentDraft.platform) {
      setActiveTab(currentDraft.platform);
    }
  }, [currentDraft]);

  const tabs: Tab[] = [
    {
      id: 'instagram',
      label: 'Instagram',
      content: <InstagramTab />,
    },
    {
      id: 'facebook',
      label: 'Facebook',
      content: <FacebookTab />,
    },
    {
      id: 'twitter',
      label: 'Twitter',
      content: <TwitterTab />,
    },
    {
      id: 'tiktok',
      label: 'TikTok',
      content: <TikTokTab />,
    },
  ];

  return <TabPanel tabs={tabs} defaultTab={activeTab} key={activeTab} />;
}
