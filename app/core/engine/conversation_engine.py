# filename: app/core/engine/conversation_engine.py
import hashlib

class ConversationEngine:
    """
    🧠 会话推演引擎 (Strategy E Core)
    负责：双星哈希计算、链式回溯判断、气泡数换算
    """
    
    def __init__(self):
        pass

    def get_msg_text(self, msg):
        """提取纯文本内容"""
        txt = ""
        for seg in msg.get('segments', []):
            if isinstance(seg, dict): txt += seg.get('content', '')
        return txt

    def compute_binary_star_hash(self, user_msgs):
        """
        计算双星指纹 (Last 2 User Messages)
        返回: (fingerprint_string, last_user_text)
        """
        if not user_msgs: return None, None
        
        last = user_msgs[-1]
        last_text = self.get_msg_text(last).strip()[:50] # 取前50字 (去噪)
        h_last = hashlib.md5(last_text.encode('utf-8')).hexdigest()
        
        if len(user_msgs) >= 2:
            prev = user_msgs[-2]
            prev_text = self.get_msg_text(prev).strip()[:50]
            h_prev = hashlib.md5(prev_text.encode('utf-8')).hexdigest()
            return f"{h_prev}+{h_last}", last_text
        else:
            # 只有一条消息时，退化为单星，但加上前缀区分
            return f"START+{h_last}", last_text

    def deduce_state(self, raw_msgs, session_data):
        """
        根据当前消息列表推演新的状态
        :param raw_msgs: 原始消息列表 (含 AI/User)
        :param session_data: 当前 SessionData 对象
        :return: (updated_session_data, status_log)
        """
        user_msgs = [m for m in raw_msgs if m.get('role') == 'User']
        has_ai_reply = len(raw_msgs) > 0 and raw_msgs[-1].get('role') == 'AI'
        
        fp, _ = self.compute_binary_star_hash(user_msgs)
        
        log = None
        
        if fp:
            chain = session_data.tail_chain
            if not chain:
                # 初始化 / 重建
                session_data.tail_chain = [fp]
                # [Task 9] 只有在计数器为0时（真·新会话）才重置为DOM数量
                # 否则保留手动设置的值（假定用户是对的）
                if session_data.user_turn_count == 0:
                    session_data.user_turn_count = len(user_msgs)
            else:
                if fp == chain[-1]:
                    pass # 无变化
                elif len(chain) >= 2 and fp == chain[-2]:
                    # 回滚检测 (History Match)
                    old_count = session_data.user_turn_count
                    session_data.user_turn_count -= 1
                    session_data.tail_chain.pop()
                    log = f"⏪ 检测到回滚，修正楼层: {old_count} -> {session_data.user_turn_count}"
                else:
                    # 新消息 (追加)
                    session_data.tail_chain.append(fp)
                    # 保持链长为 5
                    if len(session_data.tail_chain) > 5: session_data.tail_chain.pop(0)
                    session_data.user_turn_count += 1
        
        # 换算气泡数 (Output Translation)
        current_bubble_count = (session_data.user_turn_count * 2)
        if not has_ai_reply and current_bubble_count > 0:
            current_bubble_count -= 1
            
        return session_data, current_bubble_count, log

    def tag_messages(self, raw_msgs, current_bubble_count, snapshot_bubble):
        """给消息打上索引和快照标记"""
        start_bubble = current_bubble_count - len(raw_msgs) + 1
        if start_bubble < 1: start_bubble = 1
        
        for k, m in enumerate(raw_msgs): 
            m['index'] = start_bubble + k
            if m['index'] == snapshot_bubble:
                m['is_snapshot'] = True
        return raw_msgs