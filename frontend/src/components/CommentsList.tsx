import type { Comment, User } from '../lib/types';

interface CommentsListProps {
  comments: Comment[];
  users: User[];
  onRefresh: () => void;
}

export default function CommentsList({ comments, users, onRefresh }: CommentsListProps) {
  const getUserById = (id: number) => {
    return users.find(u => u.id === id);
  };

  if (comments.length === 0) {
    return (
      <div className="text-center text-gray-500 py-8">
        <p>No comments yet</p>
        <p className="text-sm mt-2">Click "+ Add Comment" to start reviewing</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {comments.map((comment) => {
        const author = getUserById(comment.author_id);
        return (
          <div key={comment.id} className="bg-gray-700 rounded-lg p-4">
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center space-x-2">
                <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-sm font-bold">
                  {author?.name.charAt(0).toUpperCase() || '?'}
                </div>
                <div>
                  <div className="font-medium text-sm">{author?.name || 'Unknown'}</div>
                  <div className="text-xs text-gray-400">
                    {new Date(comment.created_at).toLocaleString()}
                  </div>
                </div>
              </div>
              {comment.frame_number !== null && (
                <div className="text-xs text-blue-400 font-mono">
                  Frame {comment.frame_number}
                </div>
              )}
            </div>
            <p className="text-sm text-gray-300">{comment.text}</p>
            {comment.annotation_data && (
              <div className="mt-2 text-xs text-yellow-400">
                📝 Has drawing annotation
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
