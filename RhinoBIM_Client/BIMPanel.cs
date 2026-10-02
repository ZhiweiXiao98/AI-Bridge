// filename: RhinoBIM_Client/BIMPanel.cs
using System;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Eto.Forms;
using Eto.Drawing;
using Rhino.UI;

namespace RhinoBIM
{
    [System.Runtime.InteropServices.Guid("11111111-AAAA-BBBB-CCCC-123456789000")]
    public class BIMPanel : Panel
    {
        ClientWebSocket _socket;
        CancellationTokenSource _cts;
        
        TextBox _txtServerIP;
        TextBox _txtLicense; // [修改] License 输入框
        TextArea _txtLog;
        TextBox _txtInput;
        Button _btnConnect;
        Button _btnSend;

        public BIMPanel()
        {
            InitializeUI();
        }

        void InitializeUI()
        {
            var settings = RhinoBIMPlugin.Instance.Settings;
            string lastIP = settings.GetString("LastServerIP", "127.0.0.1:8765");
            string lastKey = settings.GetString("LastLicense", "vip_001"); // 默认填入一个测试 Key

            // 1. 顶部连接栏
            _txtServerIP = new TextBox { Text = lastIP, ToolTip = "SaaS Server Endpoint", Width = 140 };
            _txtLicense = new TextBox { Text = lastKey, ToolTip = "License Key (Auth)", Width = 90, PlaceholderText = "Key" };
            
            _btnConnect = new Button { Text = "Login" }; // 按钮文本改为 Login
            _btnConnect.Click += async (s, e) => await ConnectToServer();

            // 2. 日志栏
            _txtLog = new TextArea { 
                ReadOnly = true, 
                TextColor = Colors.Lime, 
                BackgroundColor = Colors.Black,
                Font = new Font(FontFamilies.Monospace, 9)
            };

            // 3. 发送栏
            _txtInput = new TextBox { PlaceholderText = "Send Request to AI..." };
            _btnSend = new Button { Text = "Send", Enabled = false };
            _btnSend.Click += async (s, e) => await SendMessage();

            // 布局
            var layout = new TableLayout
            {
                Padding = new Padding(5), Spacing = new Size(5, 5),
                Rows =
                {
                    new TableRow(new TableCell(_txtServerIP, true), _txtLicense, _btnConnect),
                    new TableRow(new TableCell(_txtLog, true)) { ScaleHeight = true },
                    new TableRow(new TableCell(_txtInput, true), _btnSend)
                }
            };
            Content = layout;
        }

        async Task ConnectToServer()
        {
            try
            {
                if (_socket != null && _socket.State == WebSocketState.Open) return;

                _socket = new ClientWebSocket();
                _cts = new CancellationTokenSource();
                
                string ip = _txtServerIP.Text.Trim();
                string key = _txtLicense.Text.Trim();
                if (!ip.StartsWith("ws://")) ip = "ws://" + ip;
                
                // === 鉴权连接 URL ===
                // 格式: ws://IP:PORT/ws/{license_key}/{device_id}
                string url = $"{ip}/ws/{key}/RhinoClient_{Guid.NewGuid().ToString().Substring(0, 5)}"; 

                // 保存记忆
                var s = RhinoBIMPlugin.Instance.Settings;
                s.SetString("LastServerIP", _txtServerIP.Text);
                s.SetString("LastLicense", _txtLicense.Text);

                Log($"🔑 Authenticating with {key}...", true);
                await _socket.ConnectAsync(new Uri(url), _cts.Token);
                
                Log($"✅ Auth Success!");
                _btnConnect.Text = "Active";
                _btnConnect.Enabled = false;
                _txtServerIP.Enabled = false;
                _txtLicense.Enabled = false;
                _btnSend.Enabled = true;

                _ = ReceiveLoop();
            }
            catch (Exception ex)
            {
                Log($"⛔ Connection Denied: {ex.Message}");
                _btnConnect.Enabled = true;
            }
        }

        async Task SendMessage()
        {
            if (_socket == null || _socket.State != WebSocketState.Open) return;
            
            string msg = _txtInput.Text;
            if (string.IsNullOrWhiteSpace(msg)) return;

            string json = $"{{\"content\": \"{msg}\"}}";
            byte[] buffer = Encoding.UTF8.GetBytes(json);
            
            try 
            {
                await _socket.SendAsync(new ArraySegment<byte>(buffer), WebSocketMessageType.Text, true, _cts.Token);
                Log($"Me: {msg}");
                _txtInput.Text = "";
            }
            catch (Exception ex)
            {
                Log($"❌ Send Error: {ex.Message}");
            }
        }

        async Task ReceiveLoop()
        {
            var buffer = new byte[65536];
            try
            {
                while (_socket.State == WebSocketState.Open)
                {
                    var result = await _socket.ReceiveAsync(new ArraySegment<byte>(buffer), _cts.Token);
                    if (result.MessageType == WebSocketMessageType.Close) break;

                    string msg = Encoding.UTF8.GetString(buffer, 0, result.Count);
                    
                    Application.Instance.AsyncInvoke(() => {
                        // 核心协议: 识别 py: 前缀
                        if (msg.StartsWith("py:"))
                        {
                            string code = msg.Substring(3);
                            RunPython(code);
                        }
                        else
                        {
                            Log($"☁️ Cloud: {msg}");
                        }
                    });
                }
            }
            catch { }
            finally 
            { 
                Application.Instance.AsyncInvoke(() => {
                    Log("⚠️ Disconnected");
                    _btnConnect.Text = "Login";
                    _btnConnect.Enabled = true;
                    _txtServerIP.Enabled = true;
                    _txtLicense.Enabled = true;
                    _btnSend.Enabled = false;
                });
            }
        }

        void RunPython(string code)
        {
            try
            {
                Log("🚀 Executing Remote Script...");
                
                var engine = Rhino.Runtime.PythonScript.Create();
                if (engine == null)
                {
                    Log("❌ Error: Python Engine Init Failed");
                    return;
                }

                engine.ExecuteScript(code);
                
                Rhino.RhinoDoc.ActiveDoc.Views.Redraw();
                Log("✅ Done");
            }
            catch (Exception ex)
            {
                Log($"❌ Error: {ex.Message}");
            }
        }

        void Log(string text, bool clear = false)
        {
            if (clear) _txtLog.Text = "";
            _txtLog.Append($"{text}\n");
        }
    }
}
