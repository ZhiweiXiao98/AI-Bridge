import asyncio
import logging
import threading
from typing import Optional, Callable

from .api_stream_models import StreamChunk, StreamStatus
from .api_stream_state import APIStreamState
from app.core.logging import get_logger

logger = get_logger("app.core.api_stream_handler", side="worker")

class APIStreamHandler:
    def __init__(self, api_source):
        self.api_source = api_source
        self.state = APIStreamState()
        self._cancel_flag = False
        self._thread: Optional[threading.Thread] = None

    @property
    def is_streaming(self) -> bool:
        return self.state.is_streaming

    def cancel(self):
        """请求取消当前流式任务（软取消）。"""
        self._cancel_flag = True

    def start_stream(self, text: str, on_chunk: Optional[Callable[[StreamChunk], None]] = None, on_complete: Optional[Callable[[StreamChunk], None]] = None, on_error: Optional[Callable[[StreamChunk], None]] = None):
        logger.info(f"[APIStreamHandler] start_stream 被调用 | text_len={len(text)}")
        if self.state.is_streaming:
            logger.warning("[APIStreamHandler] 已有流式处理在进行中")
            logger.warning("Already streaming, ignoring new request")
            return

        self._cancel_flag = False
        conv_id = ""
        if self.api_source and hasattr(self.api_source, 'conv_store'):
            conv_id = getattr(self.api_source.conv_store, 'active_id', '') or ''

        stream_id = self.state.start(conversation_id=conv_id)
        logger.info(f"[APIStreamHandler] 流式处理已启动 | stream_id={stream_id} | conv_id={conv_id}")

        if on_chunk:
            logger.debug(f"[APIStreamHandler] 发送 STARTED 信号 | stream_id={stream_id}")
            on_chunk(StreamChunk(stream_id=stream_id, content="", status=StreamStatus.STARTED, conversation_id=conv_id))

        def _run():
            logger.info(f"[APIStreamHandler] 流式线程启动 | stream_id={stream_id}")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                logger.info(f"[APIStreamHandler] 运行 _stream_loop | stream_id={stream_id}")
                loop.run_until_complete(self._stream_loop(text, stream_id, conv_id, on_chunk, on_complete, on_error))
                logger.info(f"[APIStreamHandler] _stream_loop 完成 | stream_id={stream_id}")
            except Exception as e:
                logger.error(f"[APIStreamHandler] 流式线程异�� | stream_id={stream_id} | error={e}", exc_info=True)
                logger.error(f"Stream thread error: {e}")
                self.state.fail(str(e))
                if on_error:
                    on_error(StreamChunk(stream_id=stream_id, content="", status=StreamStatus.ERROR, accumulated=self.state.accumulated_text, error_message=str(e), conversation_id=conv_id))
            finally:
                logger.info(f"[APIStreamHandler] 关闭事件循环 | stream_id={stream_id}")
                loop.close()

        self._thread = threading.Thread(target=_run, daemon=True)
        logger.info(f"[APIStreamHandler] 启动流式线程 | stream_id={stream_id}")
        self._thread.start()
        logger.info(f"[APIStreamHandler] 流式线程已启动 | stream_id={stream_id}")

    async def _stream_loop(self, text: str, stream_id: str, conv_id: str, on_chunk: Optional[Callable], on_complete: Optional[Callable], on_error: Optional[Callable]):
        logger.info(f"[Stream] 开始流式处理 | stream_id={stream_id}")
        generator = self.api_source.send_message_stream(text)
        chunk_count = 0
        try:
            logger.info(f"[Stream] 开始迭代生成器 | stream_id={stream_id}")
            async for chunk_text in generator:
                chunk_count += 1
                logger.debug(f"[Stream] 收到 chunk #{chunk_count} | len={len(chunk_text)} | stream_id={stream_id}")
                
                if self._cancel_flag:
                    self.state.cancel()
                    if on_chunk:
                        on_chunk(StreamChunk(stream_id=stream_id, content="", status=StreamStatus.CANCELLED, accumulated=self.state.accumulated_text, conversation_id=conv_id))
                    logger.info(f"[Stream] 流式处理被取消 | stream_id={stream_id}")
                    return

                self.state.append(chunk_text)
                if on_chunk:
                    on_chunk(StreamChunk(stream_id=stream_id, content=chunk_text, status=StreamStatus.STREAMING, accumulated=self.state.accumulated_text, conversation_id=conv_id))

            logger.info(f"[Stream] 流式处理完成 | stream_id={stream_id} | total_chunks={chunk_count}")
            self.state.complete()
            if on_complete:
                on_complete(StreamChunk(stream_id=stream_id, content="", status=StreamStatus.COMPLETED, accumulated=self.state.accumulated_text, conversation_id=conv_id))

        except Exception as e:
            logger.error(f"[Stream] 流式处理异常 | stream_id={stream_id} | chunks_received={chunk_count} | error={e}", exc_info=True)
            self.state.fail(str(e))
            if on_error:
                on_error(StreamChunk(stream_id=stream_id, content="", status=StreamStatus.ERROR, accumulated=self.state.accumulated_text, error_message=str(e), conversation_id=conv_id))
        finally:
            logger.info(f"[Stream] 清理生成器 | stream_id={stream_id}")
            try:
                await generator.aclose()
            except Exception as e:
                logger.warning(f"[Stream] 生成器清理异常 | stream_id={stream_id} | error={e}")
