// filename: RhinoBIM_Client/RhinoBIMPlugin.cs
using System;
using Rhino;
using Rhino.PlugIns;
using Rhino.UI;
using System.Runtime.InteropServices;

[assembly: Guid("98765432-AAAA-BBBB-CCCC-123456789000")]

namespace RhinoBIM
{
    public class RhinoBIMPlugin : PlugIn
    {
        public static RhinoBIMPlugin Instance { get; private set; }
        
        public RhinoBIMPlugin()
        {
            Instance = this;
        }

        protected override LoadReturnCode OnLoad(ref string errorMessage)
        {
            // 注册面板 (无图标版)
            Panels.RegisterPanel(this, typeof(BIMPanel), "AI Bridge", null); 
            return LoadReturnCode.Success;
        }
    }
}
