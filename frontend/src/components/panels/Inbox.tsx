import React, { useState } from 'react';
import TabPanel, { Tab } from '../common/TabPanel';
import { useApp } from '../../contexts/AppContext';

function MessagesTab() {
  const [selectedMessage, setSelectedMessage] = useState<number | null>(0);

  const conversations = [
    { id: 0, name: 'Sarah Johnson', platform: 'Instagram', time: '5m ago', preview: 'Hey! Loved your latest post 😍', unread: true, avatar: 'S' },
    { id: 1, name: 'Mike Chen', platform: 'Facebook', time: '1h ago', preview: 'Is this product still available?', unread: true, avatar: 'M' },
    { id: 2, name: 'Emma Davis', platform: 'Instagram', time: '3h ago', preview: 'Thanks for the quick response!', unread: false, avatar: 'E' },
    { id: 3, name: 'Alex Rodriguez', platform: 'Twitter', time: '1d ago', preview: 'Could you share more details?', unread: false, avatar: 'A' },
  ];

  const messages = [
    { sender: 'Sarah Johnson', text: 'Hey! Loved your latest post 😍', time: '5m ago', isMe: false },
    { sender: 'You', text: 'Thank you so much! Glad you liked it!', time: '4m ago', isMe: true },
    { sender: 'Sarah Johnson', text: 'Where did you get that outfit from?', time: '3m ago', isMe: false },
  ];

  return (
    <div className="h-full flex bg-scian-dark">
      {/* Conversation List */}
      <div className="w-80 border-r border-scian-border flex flex-col">
        <div className="p-4 border-b border-scian-border">
          <h2 className="text-lg font-semibold text-scian-text-primary mb-3">Messages</h2>
          <input
            type="text"
            placeholder="Search messages..."
            className="w-full bg-scian-darker border border-scian-border rounded px-3 py-2 text-sm text-scian-text-primary placeholder-scian-text-muted focus:border-scian-cyan focus:outline-none"
          />
        </div>

        <div className="flex-1 overflow-y-auto">
          {conversations.map((conv) => (
            <div
              key={conv.id}
              onClick={() => setSelectedMessage(conv.id)}
              className={`p-4 border-b border-scian-border cursor-pointer transition-colors ${
                selectedMessage === conv.id ? 'bg-scian-hover' : 'hover:bg-scian-panel'
              }`}
            >
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-full bg-gradient-to-r from-scian-cyan to-scian-blue flex items-center justify-center text-sm font-semibold text-white flex-shrink-0">
                  {conv.avatar}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <span className={`text-sm font-medium ${conv.unread ? 'text-scian-text-primary' : 'text-scian-text-secondary'}`}>
                      {conv.name}
                    </span>
                    <span className="text-xs text-scian-text-muted">{conv.time}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <p className={`text-sm truncate ${conv.unread ? 'text-scian-text-primary font-medium' : 'text-scian-text-secondary'}`}>
                      {conv.preview}
                    </p>
                    {conv.unread && (
                      <span className="w-2 h-2 rounded-full bg-scian-cyan flex-shrink-0 ml-2" />
                    )}
                  </div>
                  <span className="text-xs text-scian-text-muted">{conv.platform}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Message Thread */}
      <div className="flex-1 flex flex-col">
        {selectedMessage !== null ? (
          <>
            {/* Thread Header */}
            <div className="p-4 border-b border-scian-border flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-gradient-to-r from-scian-cyan to-scian-blue flex items-center justify-center text-sm font-semibold text-white">
                  {conversations[selectedMessage].avatar}
                </div>
                <div>
                  <div className="text-sm font-medium text-scian-text-primary">{conversations[selectedMessage].name}</div>
                  <div className="text-xs text-scian-text-secondary">{conversations[selectedMessage].platform}</div>
                </div>
              </div>
              <button className="text-scian-text-secondary hover:text-scian-text-primary">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                </svg>
              </button>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.isMe ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[70%] ${msg.isMe ? 'order-2' : 'order-1'}`}>
                    <div
                      className={`rounded-lg px-4 py-2 ${
                        msg.isMe
                          ? 'bg-gradient-to-r from-scian-cyan to-scian-blue text-white'
                          : 'bg-scian-panel text-scian-text-primary border border-scian-border'
                      }`}
                    >
                      <p className="text-sm">{msg.text}</p>
                    </div>
                    <span className="text-xs text-scian-text-muted mt-1 block">{msg.time}</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Reply Input */}
            <div className="p-4 border-t border-scian-border">
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Type a message..."
                  className="flex-1 bg-scian-darker border border-scian-border rounded-lg px-4 py-2 text-sm text-scian-text-primary placeholder-scian-text-muted focus:border-scian-cyan focus:outline-none"
                />
                <button className="px-4 py-2 bg-gradient-to-r from-scian-cyan to-scian-blue rounded-lg text-sm font-medium text-white hover:opacity-90 transition-opacity">
                  Send
                </button>
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-scian-text-muted">
            Select a conversation to start messaging
          </div>
        )}
      </div>
    </div>
  );
}

function CommentsTab() {
  const { setSelectedPost, focusPanel } = useApp();

  const comments = [
    { id: 1, postId: 'live-ig1', author: 'Jessica Williams', platform: 'instagram', post: 'Summer vibes ☀️ #lifestyle', comment: 'This is amazing! Where was this taken?', time: '10m ago', avatar: 'J' },
    { id: 2, postId: 'fb1', author: 'David Brown', platform: 'facebook', post: 'Product launch announcement', comment: 'Congratulations on the launch! 🎉', time: '1h ago', avatar: 'D' },
    { id: 3, postId: 'live-ig3', author: 'Lisa Anderson', platform: 'instagram', post: 'Behind the scenes 📸', comment: 'Love seeing the process!', time: '2h ago', avatar: 'L' },
    { id: 4, postId: 'tw1', author: 'Tom Wilson', platform: 'twitter', post: 'Monday motivation', comment: 'Needed this today, thanks!', time: '5h ago', avatar: 'T' },
  ];

  const handleCommentClick = (comment: typeof comments[0]) => {
    // Create a post object from the comment data
    const post = {
      id: comment.postId,
      platform: comment.platform as 'instagram' | 'facebook' | 'twitter' | 'tiktok',
      caption: comment.post,
      username: 'your_brand',
      likes: 0,
      comments: 0,
      status: 'published',
    };
    setSelectedPost(post);
    focusPanel('livefeed');
  };

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Comments</h2>
        <p className="text-scian-text-secondary text-sm">Respond to your audience</p>
      </div>

      <div className="space-y-4">
        {comments.map((comment, i) => (
          <div
            key={comment.id}
            onClick={() => handleCommentClick(comment)}
            className="bg-scian-panel border border-scian-border rounded-lg p-4 cursor-pointer hover:border-scian-green transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-scian-green/10 animate-fadeIn"
            style={{ animationDelay: `${i * 100}ms` }}
          >
            <div className="flex items-start gap-3 mb-3">
              <div className="w-10 h-10 rounded-full bg-gradient-to-r from-scian-violet to-scian-peach flex items-center justify-center text-sm font-semibold text-white flex-shrink-0">
                {comment.avatar}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-medium text-scian-text-primary">{comment.author}</span>
                  <span className="text-xs text-scian-text-secondary">· {comment.platform}</span>
                  <span className="text-xs text-scian-text-muted">· {comment.time}</span>
                </div>
                <div className="text-xs text-scian-text-secondary mb-2">
                  on <span className="italic">"{comment.post}"</span>
                </div>
                <p className="text-sm text-scian-text-primary mb-3">{comment.comment}</p>

                <div className="flex gap-2">
                  <button className="text-xs px-3 py-1 bg-scian-darker border border-scian-border rounded text-scian-text-secondary hover:text-scian-cyan hover:border-scian-cyan transition-colors">
                    Reply
                  </button>
                  <button className="text-xs px-3 py-1 bg-scian-darker border border-scian-border rounded text-scian-text-secondary hover:text-scian-text-primary transition-colors">
                    Like
                  </button>
                  <button className="text-xs px-3 py-1 bg-scian-darker border border-scian-border rounded text-scian-text-secondary hover:text-scian-peach hover:border-scian-peach transition-colors">
                    Hide
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

function MentionsTab() {
  const mentions = [
    { id: 1, author: 'Rachel Green', platform: 'Instagram', text: 'Love working with @your_brand! Best experience ever 💙', time: '30m ago', avatar: 'R', type: 'story' },
    { id: 2, author: 'Chris Martin', platform: 'Twitter', text: 'Shoutout to @your_brand for amazing customer service!', time: '2h ago', avatar: 'C', type: 'tweet' },
    { id: 3, author: 'Nina Patel', platform: 'Instagram', text: 'Thanks @your_brand for the feature! 🙏', time: '1d ago', avatar: 'N', type: 'post' },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full overflow-auto">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Mentions</h2>
        <p className="text-scian-text-secondary text-sm">See who's talking about you</p>
      </div>

      <div className="space-y-4">
        {mentions.map((mention, i) => (
          <div key={mention.id} className="bg-scian-panel border border-scian-border rounded-lg p-4 hover:border-scian-green transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-scian-green/10 animate-fadeIn cursor-pointer" style={{ animationDelay: `${i * 100}ms` }}>
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-full bg-gradient-to-r from-scian-green to-scian-cyan flex items-center justify-center text-sm font-semibold text-white flex-shrink-0">
                {mention.avatar}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-sm font-medium text-scian-text-primary">{mention.author}</span>
                  <span className="text-xs px-2 py-0.5 bg-scian-darker rounded text-scian-text-secondary">{mention.type}</span>
                  <span className="text-xs text-scian-text-muted">· {mention.time}</span>
                </div>
                <p className="text-sm text-scian-text-primary mb-3">{mention.text}</p>
                <div className="flex gap-2">
                  <button className="text-xs px-3 py-1 bg-gradient-to-r from-scian-green to-scian-cyan rounded text-white hover:opacity-90 transition-opacity">
                    Repost
                  </button>
                  <button className="text-xs px-3 py-1 bg-scian-darker border border-scian-border rounded text-scian-text-secondary hover:text-scian-text-primary transition-colors">
                    View
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

export default function Inbox() {
  const tabs: Tab[] = [
    {
      id: 'messages',
      label: 'Messages',
      content: <MessagesTab />,
    },
    {
      id: 'comments',
      label: 'Comments',
      content: <CommentsTab />,
    },
    {
      id: 'mentions',
      label: 'Mentions',
      content: <MentionsTab />,
    },
  ];

  return <TabPanel tabs={tabs} defaultTab="messages" />;
}
