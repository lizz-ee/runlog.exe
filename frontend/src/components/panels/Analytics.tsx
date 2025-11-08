import React from 'react';
import TabPanel, { Tab } from '../common/TabPanel';

function OverviewTab() {
  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-6 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Overview</h2>
        <p className="text-scian-text-secondary text-sm">Track your performance</p>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        {[
          { label: 'Total Posts', value: '24', color: 'from-scian-cyan to-scian-blue', icon: '📝', glowColor: 'scian-cyan' },
          { label: 'Engagement', value: '3.2K', color: 'from-scian-peach to-scian-violet', icon: '❤️', glowColor: 'scian-peach' },
          { label: 'Followers', value: '1.2K', color: 'from-scian-blue to-scian-violet', icon: '👥', glowColor: 'scian-blue' },
          { label: 'Growth', value: '+12%', color: 'from-scian-green to-scian-cyan', icon: '📈', glowColor: 'scian-green' },
        ].map((stat, i) => (
          <div
            key={stat.label}
            className={`bg-scian-panel rounded-lg p-4 border border-scian-border hover:border-${stat.glowColor} transition-all cursor-pointer group hover:scale-105 hover:shadow-lg hover:shadow-${stat.glowColor}/20 animate-fadeIn relative overflow-hidden`}
            style={{ animationDelay: `${i * 100}ms` }}
          >
            {/* Gradient background on hover */}
            <div className={`absolute inset-0 bg-gradient-to-br ${stat.color} opacity-0 group-hover:opacity-5 transition-opacity`} />

            <div className="relative z-10">
              <div className="flex items-center justify-between mb-2">
                <div className="text-sm text-scian-text-secondary font-medium">{stat.label}</div>
                <span className="text-2xl opacity-40 group-hover:opacity-100 transition-opacity">{stat.icon}</span>
              </div>
              <div className={`text-3xl font-bold bg-gradient-to-r ${stat.color} bg-clip-text text-transparent group-hover:scale-110 transition-transform origin-left`}>
                {stat.value}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Chart placeholder with gradient */}
      <div className="bg-scian-panel rounded-lg p-6 border border-scian-border h-56 flex items-center justify-center relative overflow-hidden group hover:border-scian-cyan transition-all animate-fadeIn" style={{ animationDelay: '400ms' }}>
        <div className="absolute inset-0 bg-gradient-to-br from-scian-cyan/5 via-scian-blue/5 to-scian-violet/5 opacity-50" />
        <div className="relative z-10 text-center">
          <div className="text-4xl mb-3 opacity-20">📊</div>
          <div className="text-scian-text-muted text-sm">Performance chart coming soon</div>
          <div className="text-scian-text-muted text-xs mt-1">Visual analytics and insights</div>
        </div>
      </div>
    </div>
  );
}

function EngagementTab() {
  const posts = [
    { title: 'Summer launch photo', likes: 245, comments: 32, shares: 12, platform: 'Instagram', platformColor: 'platform-instagram-mid', emoji: '📸' },
    { title: 'Behind the scenes video', likes: 189, comments: 28, shares: 8, platform: 'TikTok', platformColor: 'platform-tiktok-accent', emoji: '🎬' },
    { title: 'Product announcement', likes: 156, comments: 19, shares: 15, platform: 'Facebook', platformColor: 'platform-facebook', emoji: '📢' },
    { title: 'Weekly thread', likes: 134, comments: 45, shares: 23, platform: 'Twitter', platformColor: 'platform-twitter', emoji: '🐦' },
  ];

  const getTotalEngagement = (post: typeof posts[0]) => post.likes + post.comments + post.shares;

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-6 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Engagement</h2>
        <p className="text-scian-text-secondary text-sm">Post performance breakdown</p>
      </div>

      <div className="space-y-4">
        {posts.map((post, i) => (
          <div
            key={i}
            className="bg-scian-panel border border-scian-border rounded-lg p-4 hover:border-scian-cyan transition-all cursor-pointer hover:scale-[1.02] hover:shadow-lg hover:shadow-scian-cyan/10 animate-fadeIn group relative overflow-hidden"
            style={{ animationDelay: `${i * 100}ms` }}
          >
            {/* Platform accent bar */}
            <div className={`absolute left-0 top-0 bottom-0 w-1 bg-${post.platformColor} group-hover:w-2 transition-all`} />

            <div className="pl-3">
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-center gap-2">
                  <span className="text-xl opacity-60 group-hover:opacity-100 transition-opacity">{post.emoji}</span>
                  <h3 className="text-scian-text-primary font-semibold">{post.title}</h3>
                </div>
                <span className={`text-xs px-2 py-1 rounded-full bg-${post.platformColor}/10 text-${post.platformColor} border border-${post.platformColor}/20 font-medium`}>
                  {post.platform}
                </span>
              </div>

              {/* Engagement stats */}
              <div className="grid grid-cols-4 gap-3 mb-3">
                <div className="bg-scian-darker rounded-lg p-2 border border-scian-border hover:border-scian-peach transition-colors">
                  <div className="text-xs text-scian-text-muted mb-1">Likes</div>
                  <div className="text-lg font-bold text-scian-peach">{post.likes}</div>
                </div>
                <div className="bg-scian-darker rounded-lg p-2 border border-scian-border hover:border-scian-blue transition-colors">
                  <div className="text-xs text-scian-text-muted mb-1">Comments</div>
                  <div className="text-lg font-bold text-scian-blue">{post.comments}</div>
                </div>
                <div className="bg-scian-darker rounded-lg p-2 border border-scian-border hover:border-scian-green transition-colors">
                  <div className="text-xs text-scian-text-muted mb-1">Shares</div>
                  <div className="text-lg font-bold text-scian-green">{post.shares}</div>
                </div>
                <div className="bg-scian-darker rounded-lg p-2 border border-scian-border hover:border-scian-cyan transition-colors">
                  <div className="text-xs text-scian-text-muted mb-1">Total</div>
                  <div className="text-lg font-bold text-scian-cyan">{getTotalEngagement(post)}</div>
                </div>
              </div>

              {/* Progress bar */}
              <div className="bg-scian-darker rounded-full h-2 overflow-hidden">
                <div
                  className={`h-full bg-gradient-to-r from-scian-peach via-scian-blue to-scian-green transition-all`}
                  style={{ width: `${Math.min((getTotalEngagement(post) / 300) * 100, 100)}%` }}
                />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AudienceTab() {
  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-6 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Audience</h2>
        <p className="text-scian-text-secondary text-sm">Know your followers</p>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-6">
        <div className="bg-scian-panel rounded-lg p-5 border border-scian-border hover:border-scian-cyan transition-all cursor-pointer hover:scale-105 hover:shadow-lg hover:shadow-scian-cyan/10 animate-fadeIn group relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-br from-scian-cyan/5 to-scian-blue/5 opacity-0 group-hover:opacity-100 transition-opacity" />
          <div className="relative z-10">
            <div className="text-sm text-scian-text-secondary mb-3 font-medium">Top Location</div>
            <div className="text-2xl font-bold text-scian-text-primary mb-2">🌎 United States</div>
            <div className="text-xs text-scian-cyan font-medium">32% of audience</div>
          </div>
        </div>
        <div className="bg-scian-panel rounded-lg p-5 border border-scian-border hover:border-scian-violet transition-all cursor-pointer hover:scale-105 hover:shadow-lg hover:shadow-scian-violet/10 animate-fadeIn group relative overflow-hidden" style={{ animationDelay: '100ms' }}>
          <div className="absolute inset-0 bg-gradient-to-br from-scian-violet/5 to-scian-peach/5 opacity-0 group-hover:opacity-100 transition-opacity" />
          <div className="relative z-10">
            <div className="text-sm text-scian-text-secondary mb-3 font-medium">Peak Time</div>
            <div className="text-2xl font-bold text-scian-text-primary mb-2">🕐 2:00 PM</div>
            <div className="text-xs text-scian-violet font-medium">Best engagement</div>
          </div>
        </div>
      </div>

      <div className="bg-scian-panel rounded-lg p-5 border border-scian-border hover:border-scian-cyan transition-all animate-fadeIn" style={{ animationDelay: '200ms' }}>
        <div className="text-sm text-scian-text-secondary mb-4 font-semibold flex items-center justify-between">
          <span>Age Distribution</span>
          <span className="text-xs text-scian-cyan">1,245 total followers</span>
        </div>
        <div className="space-y-4">
          {[
            { range: '18-24', percent: 35, color: 'from-scian-cyan to-scian-blue' },
            { range: '25-34', percent: 42, color: 'from-scian-blue to-scian-violet' },
            { range: '35-44', percent: 18, color: 'from-scian-violet to-scian-peach' },
            { range: '45+', percent: 5, color: 'from-scian-peach to-scian-peach' },
          ].map((age, i) => (
            <div key={age.range} className="group">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm text-scian-text-primary font-medium">{age.range}</span>
                <span className="text-sm text-scian-cyan font-bold">{age.percent}%</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex-1 bg-scian-darker rounded-full h-3 overflow-hidden">
                  <div
                    className={`h-full bg-gradient-to-r ${age.color} transition-all duration-1000 ease-out rounded-full group-hover:animate-pulse`}
                    style={{ width: `${age.percent}%`, animationDelay: `${i * 200}ms` }}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-6 grid grid-cols-3 gap-4">
        {[
          { label: 'Male', value: '48%', icon: '👨', color: 'scian-blue' },
          { label: 'Female', value: '51%', icon: '👩', color: 'scian-peach' },
          { label: 'Other', value: '1%', icon: '⚧', color: 'scian-violet' },
        ].map((demo, i) => (
          <div
            key={demo.label}
            className={`bg-scian-panel rounded-lg p-4 border border-scian-border hover:border-${demo.color} transition-all cursor-pointer hover:scale-105 hover:shadow-lg hover:shadow-${demo.color}/10 animate-fadeIn`}
            style={{ animationDelay: `${300 + i * 100}ms` }}
          >
            <div className="text-2xl mb-2 text-center opacity-60">{demo.icon}</div>
            <div className={`text-xl font-bold text-${demo.color} text-center mb-1`}>{demo.value}</div>
            <div className="text-xs text-scian-text-secondary text-center">{demo.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Analytics() {
  const tabs: Tab[] = [
    {
      id: 'overview',
      label: 'Overview',
      content: <OverviewTab />,
    },
    {
      id: 'engagement',
      label: 'Engagement',
      content: <EngagementTab />,
    },
    {
      id: 'audience',
      label: 'Audience',
      content: <AudienceTab />,
    },
  ];

  return <TabPanel tabs={tabs} defaultTab="overview" />;
}
