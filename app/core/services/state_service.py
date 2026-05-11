# filename: app/core/services/state_service.py
import json
import os
import time

STATE_FILE = "session_states.json"

class SessionData:
    def __init__(self, user_cnt=0, snap_bubble=0, tail_chain=None):
        self.user_turn_count = user_cnt   # 用户发起的轮数 (Round)
        self.snapshot_bubble = snap_bubble # 用户标记的快照点 (Bubble Count)
        self.tail_chain = tail_chain or [] # 双星指纹链 (Last 5)

class StateService:
    def __init__(self):
        self.sessions = {} # {chat_id: SessionData}
        self.last_sync_time = 0
        self.last_emitted_turn = -1
        self.last_emitted_snap = -1
        self._load_states()

    def _load_states(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for cid, sdata in data.items():
                        # 兼容旧数据：如果没有 user_turn_count，则重置为 0
                        self.sessions[cid] = SessionData(
                            sdata.get('user_turn_count', 0), 
                            sdata.get('snapshot_bubble', 0),
                            sdata.get('tail_chain', [])
                        )
        except: pass

    def save_states(self):
        data = {}
        for cid, s in self.sessions.items():
            data[cid] = {
                'user_turn_count': s.user_turn_count, 
                'snapshot_bubble': s.snapshot_bubble,
                'tail_chain': s.tail_chain
            }
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f: 
                json.dump(data, f, indent=2, ensure_ascii=False)
        except: pass

    def get_session(self, chat_id):
        if chat_id not in self.sessions:
            self.sessions[chat_id] = SessionData()
        return self.sessions[chat_id]

    def update_user_turn(self, chat_id, new_count, new_chain):
        s = self.get_session(chat_id)
        if new_count != s.user_turn_count or new_chain != s.tail_chain:
            s.user_turn_count = new_count
            s.tail_chain = new_chain
            self.save_states()
            return True
        return False

    def set_manual_bubble_count(self, chat_id, bubble_num):
        """用户手动修正气泡数 -> 反推用户轮数"""
        s = self.get_session(chat_id)
        # 假设：Turn = User * 2. 所以 User = Turn / 2
        # 这只是一个近似修正，真正的链条会在下一次 Worker 扫描时重建
        s.user_turn_count = bubble_num // 2
        s.tail_chain = [] # 手动干预后，清空链条强制重建
        self.save_states()

    def set_snapshot(self, chat_id, bubble_num):
        s = self.get_session(chat_id)
        s.snapshot_bubble = bubble_num
        self.save_states()

    def should_emit_sync(self, chat_id, current_visible_bubble, force=False):
        """
        判断是否需要同步状态
        :param current_visible_bubble: Worker 计算出的当前气泡数
        """
        s = self.get_session(chat_id)
        now = time.time()
        
        needs_sync = False
        if force:
            needs_sync = True
        elif (now - self.last_sync_time > 2):
            needs_sync = True
        elif (current_visible_bubble != self.last_emitted_turn) or (s.snapshot_bubble != self.last_emitted_snap):
            needs_sync = True
            
        if needs_sync:
            self.last_emitted_turn = current_visible_bubble
            self.last_emitted_snap = s.snapshot_bubble
            self.last_sync_time = now
            
        return needs_sync, s.snapshot_bubble