import React from 'react';
import TabPanel, { Tab } from '../common/TabPanel';

function MonthViewTab() {
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  // Mock scheduled posts with platform colors
  const scheduledDays = [
    { day: 5, platform: 'instagram', count: 2 },
    { day: 12, platform: 'facebook', count: 1 },
    { day: 15, platform: 'twitter', count: 3 },
    { day: 18, platform: 'tiktok', count: 1 },
    { day: 22, platform: 'instagram', count: 1 },
    { day: 28, platform: 'facebook', count: 2 },
  ];

  const getScheduledForDay = (day: number) => {
    return scheduledDays.filter(s => s.day === day);
  };

  const getPlatformColor = (platform: string) => {
    const colors: Record<string, string> = {
      instagram: 'from-platform-instagram-start via-platform-instagram-mid to-platform-instagram-end',
      facebook: 'from-platform-facebook to-platform-facebook',
      twitter: 'from-platform-twitter to-platform-twitter',
      tiktok: 'from-platform-tiktok-accent to-platform-tiktok-accent',
    };
    return colors[platform] || 'from-scian-cyan to-scian-blue';
  };

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-6 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Month View</h2>
        <p className="text-scian-text-secondary text-sm">Plan your posts visually</p>
      </div>

      {/* Month navigation */}
      <div className="flex items-center justify-between mb-6 animate-fadeIn" style={{ animationDelay: '100ms' }}>
        <button className="px-4 py-2 bg-scian-panel rounded-lg hover:bg-scian-hover text-scian-text-primary border border-scian-border hover:border-scian-cyan transition-all hover:scale-105 hover:shadow-lg hover:shadow-scian-cyan/20">
          ←
        </button>
        <span className="font-semibold text-lg text-scian-text-primary">October 2025</span>
        <button className="px-4 py-2 bg-scian-panel rounded-lg hover:bg-scian-hover text-scian-text-primary border border-scian-border hover:border-scian-cyan transition-all hover:scale-105 hover:shadow-lg hover:shadow-scian-cyan/20">
          →
        </button>
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-3">
        {days.map((day, i) => (
          <div key={day} className="text-center text-xs text-scian-text-secondary font-semibold py-2 animate-fadeIn" style={{ animationDelay: `${i * 50}ms` }}>
            {day}
          </div>
        ))}

        {[...Array(35)].map((_, i) => {
          const dayNum = (i % 31) + 1;
          const scheduled = getScheduledForDay(dayNum);
          const hasScheduled = scheduled.length > 0;

          return (
            <div
              key={i}
              className={`aspect-square bg-scian-panel rounded-lg border transition-all cursor-pointer relative group animate-fadeIn ${
                hasScheduled
                  ? 'border-scian-cyan hover:border-scian-cyan hover:shadow-lg hover:shadow-scian-cyan/20'
                  : 'border-scian-border hover:border-scian-cyan/50'
              } hover:scale-105 hover:bg-scian-hover`}
              style={{ animationDelay: `${(i + 7) * 20}ms` }}
            >
              <div className="p-2 h-full flex flex-col">
                <div className={`text-xs font-medium ${hasScheduled ? 'text-scian-text-primary' : 'text-scian-text-secondary'}`}>
                  {dayNum}
                </div>
                {hasScheduled && (
                  <div className="flex-1 flex flex-col justify-center items-center gap-1 mt-1">
                    {scheduled.map((s, idx) => (
                      <div
                        key={idx}
                        className={`w-1.5 h-1.5 rounded-full bg-gradient-to-r ${getPlatformColor(s.platform)} animate-pulse`}
                        style={{ animationDelay: `${idx * 200}ms` }}
                      />
                    ))}
                    <div className="text-[10px] text-scian-cyan font-medium mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      {scheduled.reduce((acc, s) => acc + s.count, 0)} posts
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WeekViewTab() {
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const hours = ['9 AM', '12 PM', '3 PM', '6 PM'];

  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Week View</h2>
        <p className="text-scian-text-secondary text-sm">Detailed weekly schedule</p>
      </div>

      <div className="grid grid-cols-7 gap-2">
        {days.map((day) => (
          <div key={day} className="text-center text-xs text-scian-text-secondary font-medium py-2">
            {day}
          </div>
        ))}
        {days.map((day, dayIndex) => (
          <div key={day} className="space-y-2">
            {hours.map((hour, hourIndex) => (
              <div
                key={hour}
                className="bg-scian-panel border border-scian-border rounded p-2 hover:border-scian-blue transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-scian-blue/20 cursor-pointer h-16 animate-fadeIn"
                style={{ animationDelay: `${(dayIndex * 4 + hourIndex) * 30}ms` }}
              >
                <div className="text-xs text-scian-text-muted">{hour}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function ListViewTab() {
  const scheduled = [
    { date: 'Mon, Oct 28 - 10:00 AM', content: 'Monday motivation post', platform: 'Instagram', status: 'scheduled', platformColor: 'platform-instagram-mid' },
    { date: 'Mon, Oct 28 - 2:00 PM', content: 'Product feature highlight', platform: 'Facebook', status: 'scheduled', platformColor: 'platform-facebook' },
    { date: 'Tue, Oct 29 - 9:00 AM', content: 'Behind the scenes video', platform: 'TikTok', status: 'scheduled', platformColor: 'platform-tiktok-accent' },
    { date: 'Wed, Oct 30 - 11:00 AM', content: 'Customer testimonial', platform: 'Twitter', status: 'scheduled', platformColor: 'platform-twitter' },
    { date: 'Thu, Oct 31 - 3:00 PM', content: 'Weekly roundup', platform: 'Instagram', status: 'scheduled', platformColor: 'platform-instagram-mid' },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-6 animate-fadeIn">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">List View</h2>
        <p className="text-scian-text-secondary text-sm">All scheduled posts</p>
      </div>

      <div className="space-y-4">
        {scheduled.map((post, i) => (
          <div
            key={i}
            className="bg-scian-panel border border-scian-border rounded-lg p-4 hover:border-scian-cyan transition-all cursor-pointer hover:scale-[1.02] hover:shadow-lg hover:shadow-scian-cyan/10 animate-fadeIn group relative overflow-hidden"
            style={{ animationDelay: `${i * 100}ms` }}
          >
            {/* Platform color accent bar */}
            <div className={`absolute left-0 top-0 bottom-0 w-1 bg-${post.platformColor} group-hover:w-2 transition-all`} />

            <div className="pl-3">
              <div className="flex justify-between items-start mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-scian-cyan">{post.date}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full bg-${post.platformColor}/10 text-${post.platformColor} border border-${post.platformColor}/20 font-medium`}>
                    {post.platform}
                  </span>
                </div>
                <div className="px-2 py-0.5 bg-scian-green/20 rounded text-xs text-scian-green border border-scian-green/30 font-medium">
                  Scheduled
                </div>
              </div>
              <p className="text-scian-text-primary mb-4 font-medium">{post.content}</p>
              <div className="flex gap-2">
                <button className="text-xs px-3 py-1.5 bg-scian-darker rounded-lg text-scian-text-secondary hover:text-scian-cyan hover:bg-scian-cyan/10 transition-all border border-scian-border hover:border-scian-cyan">
                  Edit
                </button>
                <button className="text-xs px-3 py-1.5 bg-scian-darker rounded-lg text-scian-text-secondary hover:text-scian-text-primary transition-all border border-scian-border hover:border-scian-border">
                  View
                </button>
                <button className="text-xs px-3 py-1.5 bg-scian-darker rounded-lg text-scian-text-secondary hover:text-scian-peach hover:bg-scian-peach/10 transition-all border border-scian-border hover:border-scian-peach ml-auto">
                  Delete
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Calendar() {
  const tabs: Tab[] = [
    {
      id: 'month',
      label: 'Month',
      content: <MonthViewTab />,
    },
    {
      id: 'week',
      label: 'Week',
      content: <WeekViewTab />,
    },
    {
      id: 'list',
      label: 'List',
      content: <ListViewTab />,
    },
  ];

  return <TabPanel tabs={tabs} defaultTab="month" />;
}
