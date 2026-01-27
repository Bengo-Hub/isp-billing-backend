# MikroTik Provisioning Guide - Codevertex ISP Billing Platform

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Provisioning Workflow](#provisioning-workflow)
4. [Command Generation & Execution](#command-generation--execution)
5. [Token-Based Authentication](#token-based-authentication)
6. [Live Streaming & WebSocket](#live-streaming--websocket)
7. [Frontend Integration](#frontend-integration)
8. [Backend Services](#backend-services)
9. [Troubleshooting](#troubleshooting)

## Overview

The Codevertex ISP Billing platform provides a comprehensive, automated provisioning system for MikroTik routers. This system enables ISP providers to configure and manage MikroTik devices remotely with minimal manual intervention, supporting both Hotspot and PPPoE services with advanced features like anti-sharing protection, custom subnets, and bandwidth management.

### Key Features

- **Automated Configuration**: Complete router setup with a single command
- **Token-Based Security**: Secure provisioning with time-limited access tokens
- **Live Streaming**: Real-time log display via WebSocket connections
- **Device Scanning**: Automatic detection of router interfaces and services
- **Multi-Service Support**: Configure Hotspot, PPPoE, or both simultaneously
- **Error Handling**: Automatic rollback on failures with detailed error reporting
- **Network Calculation**: Automatic gateway and DHCP pool configuration
- **Session Management**: Track provisioning progress with unique session IDs
- **Reprovisioning**: Seamless reconfiguration of existing routers

## Architecture

The provisioning system is built on a modular architecture, separating concerns across multiple specialized modules:

### Backend Modules

1. **ProvisioningService** (`app/services/provisioning_service.py`)
   - Main orchestrator for the entire provisioning workflow
   - Manages session lifecycle and state transitions
   - Coordinates between all other modules
   - Handles error recovery and rollback operations

2. **Bootstrap Module** (`app/api/v1/provisioning/bootstrap.py`)
   - Generates provisioning commands with embedded access tokens
   - Creates RouterOS script files (.rsc) for initial device setup
   - Validates token permissions before script download
   - Logs provisioning attempts for audit purposes

3. **Network Module** (`app/api/v1/provisioning/network.py`)
   - Calculates network configurations (gateway, DHCP pool, subnet mask)
   - Validates CIDR notations and IP address ranges
   - Generates network-specific RouterOS commands
   - Ensures no IP conflicts with existing configurations

4. **Workflow Module** (`app/api/v1/provisioning/workflow.py`)
   - Orchestrates the complete provisioning workflow
   - Manages multi-step configuration process
   - Tracks session status and progress percentage
   - Handles concurrent provisioning sessions

5. **Stream Module** (`app/api/v1/provisioning/stream.py`)
   - Provides WebSocket endpoints for real-time log streaming
   - Manages WebSocket connection lifecycle
   - Broadcasts provisioning events to connected clients
   - Handles auto-reconnection and connection failures

6. **Device Scan Module** (`app/api/v1/provisioning/device_scan.py`)
   - Scans MikroTik devices for available interfaces
   - Detects existing services (Hotspot, PPPoE, DHCP)
   - Retrieves system information (CPU, memory, RouterOS version)
   - Validates router compatibility before provisioning

7. **MikroTik Integration** (`app/integrations/mikrotik.py`)
   - RouterOS API client for command execution
   - Connection management and authentication
   - Command result parsing and error handling
   - Support for both API and SSH connections

### Frontend Components

1. **ProvisioningStepper** (`components/provisioning/ProvisioningStepper.tsx`)
   - Visual step indicator for provisioning progress
   - Interactive navigation between completed steps
   - Status indicators for each step (pending, active, completed)

2. **ConnectionStep** (`components/provisioning/ConnectionStep.tsx`)
   - Initial configuration form (router identity, API port, interface)
   - Command generation trigger
   - Loading state during command generation

3. **DeviceDetailsStep** (`components/provisioning/DeviceDetailsStep.tsx`)
   - Displays generated provisioning command
   - Copy-to-clipboard functionality
   - Instructions for command execution
   - Device connection status monitoring
   - Automatic device scanning after connection

4. **ServiceSetupStep** (`components/provisioning/ServiceSetupStep.tsx`)
   - Service selection (Hotspot, PPPoE, both)
   - Interface/port selection with multi-select
   - Network configuration (custom subnet, anti-sharing)
   - Configuration validation before submission

5. **LiveProvisioningLog** (`components/provisioning/LiveProvisioningLog.tsx`)
   - WebSocket connection for real-time logs
   - Console-style log display with color coding
   - Auto-scroll to latest log entries
   - Connection status indicators
   - Session progress percentage display

6. **Provisioning Store** (`lib/store/provisioning.ts`)
   - Centralized state management for provisioning workflow
   - Session tracking and configuration persistence
   - API integration for provisioning endpoints
   - Device connection status management

## Provisioning Workflow

The provisioning workflow consists of distinct phases, each with specific responsibilities and outcomes.

### Phase 1: Initial Setup (First-Time Provisioning)

#### **Step 1: Connection Configuration**
**Purpose**: Gather basic router information and prepare for provisioning

**Actions**:
1. User fills in router details:
   - **Router Identity**: Friendly name for the device (e.g., "MikroTik-Branch-1")
   - **API Port**: RouterOS API port (default: 8728)
   - **WAN Interface**: Interface connected to the internet (e.g., "ether1")

2. Click "Next" to generate provisioning command

3. **Backend Process**:
   - Generates a unique provisioning token with limited permissions
   - Token includes: `user_id`, `router_id`, `permissions`, `expiry (1 hour)`
   - Creates provisioning command with embedded token
   - Returns command to frontend for user execution

**Frontend State**:
- `isGeneratingCommand`: true during command generation
- `command`: Stores the generated provisioning command
- `token`: Stores the access token for script download

**Backend Endpoint**: `GET /provisioning/bootstrap/command`
```
Parameters:
  - identity: Router name
  - api_port: API port number
  - interface: WAN interface name
Returns:
  - command: Complete provisioning command
  - script_url: URL for script download
  - token: Access token
  - expires_in: Token expiry time (seconds)
```

#### **Step 2: Device Details & Command Execution**
**Purpose**: Connect the router to the billing system

**Actions**:
1. **Display Provisioning Command**:
   ```routeros
   /tool fetch mode=https url="https://[DOMAIN]/provisioning/bootstrap/script?token=[TOKEN]&identity=[IDENTITY]&api_port=[PORT]&interface=[INTERFACE]" dst-path=codevertex.rsc; delay 2s; import codevertex.rsc;
   ```

2. **User Execution**:
   - Copy command to clipboard
   - Open MikroTik terminal (via Winbox, SSH, or web interface)
   - Paste and execute the command
   - Router downloads and runs the bootstrap script

3. **Bootstrap Script Actions** (.rsc file):
   ```routeros
   ; Set router identity
   /system/identity/set name=[IDENTITY]
   
   ; Enable API access
   /ip/service/set api disabled=no port=[API_PORT]
   
   ; Enable Winbox for remote access
   /ip/service/set winbox disabled=no
   
   ; Secure SSH with custom port
   /ip/service/set ssh port=2222
   
   ; Log completion
   :log info message="Codevertex bootstrap completed"
   ```

4. **Device Connection Verification**:
   - Frontend polls backend to check device connectivity
   - Backend attempts API connection to router
   - On success, proceeds to device scanning

**Frontend State**:
- `deviceConnected`: false → true when connection succeeds
- `isScanningDevice`: true during interface scanning

**Backend Process**:
- Token verification for script download
- Script generation with user-specific parameters
- Audit logging of provisioning attempts
- Connection validation via RouterOS API

#### **Step 3: Service Configuration & Provisioning**
**Purpose**: Configure Hotspot/PPPoE services and complete setup

**User Configuration Options**:

1. **Service Selection**:
   - ☑ Enable Hotspot
   - ☑ Enable PPPoE
   - ☑ Enable Anti-Sharing Protection

2. **Network Configuration**:
   - **Use Custom Subnet**: No (default: 192.168.88.0/24)
   - **Subnet Address**: 192.168.88.0
   - **CIDR**: /24
   - **Auto-calculated Gateway**: 192.168.88.1
   - **Auto-calculated DHCP Pool**: 192.168.88.2 - 192.168.88.254

3. **Interface Selection**:
   - **Available Interfaces**: Retrieved from router scan
   - **Selected Ports**: ether2, ether3, ether4, ether5, etc.
   - **Excluded Port**: WAN interface (ether1)

**Device Scanning Process**:
1. **Backend connects to router** via API
2. **Retrieves device information**:
   - Interface list (ether1, ether2, sfp1, etc.)
   - Existing services (Hotspot, PPPoE, DHCP)
   - Current subnet configuration
   - System info (CPU, memory, RouterOS version)
3. **Returns scanned data** to frontend
4. **Frontend populates** configuration options

**Configuration Submission**:
1. User clicks "Configure Services"
2. **Frontend sends** complete configuration to backend
3. **Backend creates** provisioning session with unique `session_id`
4. **Returns** `session_id` for live log streaming

**Provisioning Execution**:
The backend executes a series of RouterOS commands in sequence:

**A. Bridge Configuration**:
```routeros
/interface bridge add name=codevertex-bridge protocol-mode=none
/interface bridge port add bridge=codevertex-bridge interface=ether2
/interface bridge port add bridge=codevertex-bridge interface=ether3
... (for each selected port)
```

**B. IP Configuration**:
```routeros
/ip address add address=192.168.88.1/24 interface=codevertex-bridge
/ip pool add name=codevertex-pool ranges=192.168.88.2-192.168.88.254
```

**C. DHCP Server**:
```routeros
/ip dhcp-server add interface=codevertex-bridge address-pool=codevertex-pool disabled=no
/ip dhcp-server network add address=192.168.88.0/24 gateway=192.168.88.1 dns-server=8.8.8.8,8.8.4.4
```

**D. DNS Configuration**:
```routeros
/ip dns set servers=8.8.8.8,8.8.4.4 allow-remote-requests=yes
```

**E. Hotspot Setup** (if enabled):
```routeros
/ip hotspot profile add name=codevertex-profile use-radius=yes
/ip hotspot user profile add name=default-hotspot
/ip hotspot add interface=codevertex-bridge address-pool=codevertex-pool profile=codevertex-profile disabled=no
```

**F. PPPoE Server** (if enabled):
```routeros
/interface pppoe-server server add interface=codevertex-bridge service-name=codevertex-pppoe authentication=pap,chap,mschap1,mschap2 disabled=no
/ppp profile add name=codevertex-pppoe local-address=192.168.88.1 use-encryption=yes
```

**G. RADIUS Configuration**:
```routeros
/radius add service=hotspot,pppoe address=[BILLING_SERVER_IP] secret=[RADIUS_SECRET] timeout=3000
/radius add service=hotspot,pppoe address=[BILLING_SERVER_IP] secret=[RADIUS_SECRET] timeout=3000
```

**H. Firewall & NAT**:
```routeros
/ip firewall filter add chain=input action=accept connection-state=established,related
/ip firewall filter add chain=input action=accept src-address=192.168.88.0/24
/ip firewall filter add chain=input action=drop
/ip firewall nat add chain=srcnat action=masquerade out-interface=ether1
```

**I. Anti-Sharing Rules** (if enabled):
```routeros
/ip firewall mangle add chain=forward action=change-ttl new-ttl=64 ttl=65 protocol=tcp
/ip firewall mangle add chain=forward action=change-ttl new-ttl=64 ttl=65 protocol=udp
```

**J. Queue Configuration**:
```routeros
/queue tree add name=codevertex-main parent=global max-limit=100M
/queue tree add name=codevertex-download parent=codevertex-main max-limit=50M
/queue tree add name=codevertex-upload parent=codevertex-main max-limit=50M
```

**K. System Configuration**:
```routeros
/system clock set time-zone-name=UTC
/system ntp client set enabled=yes primary-ntp=pool.ntp.org
/system logging add topics=info action=memory
```

**Live Log Streaming**:
- Each command execution is logged and streamed via WebSocket
- Frontend displays logs in real-time with color coding:
  - **Green**: Success
  - **Yellow**: Warning
  - **Red**: Error
  - **Blue**: Info
- Progress percentage updates after each major step

**Completion**:
- Session status changes to `COMPLETED`
- All services are configured and running
- Router is ready for user authentication via RADIUS

### Phase 2: Reprovisioning (Existing Routers)

**Differences from First-Time Provisioning**:

1. **Step 1 is Skipped**: Router is already bootstrapped, no command generation needed
2. **Step 2 Starts Directly**: Device connection check begins immediately
3. **Existing Configuration Backup**: System backs up current config before changes
4. **Selective Updates**: Only updates changed configuration items
5. **Minimal Downtime**: Services remain active during reconfiguration where possible

**Reprovisioning Workflow**:
1. User clicks "Reprovision" from router list
2. Frontend navigates to `/routers/provision?reprovision=[ROUTER_ID]`
3. System loads existing router configuration
4. User can modify:
   - Service selection (enable/disable Hotspot or PPPoE)
   - Network configuration (subnet, CIDR)
   - Interface selection (add/remove ports)
   - Anti-sharing settings
5. Provisioning executes only changed configurations
6. Live logs show update progress
7. Rollback available if errors occur

## Command Generation & Execution

### The Provisioning Command Structure

The provisioning command is the core of the system, enabling automated router configuration with a single copy-paste operation.

**Full Command Example:**
```routeros
/tool fetch mode=https url="https://billing.example.com/provisioning/bootstrap/script?token=eyJ0eXAi...&identity=MikroTik-Branch-1&api_port=8728&interface=ether1" dst-path=codevertex.rsc; delay 2s; import codevertex.rsc;
```

**Command Components:**

1. **`/tool fetch mode=https`**
   - Uses MikroTik's file download tool
   - `mode=https` ensures secure HTTPS connection
   - Supports SSL/TLS certificate validation

2. **`url="..."`**
   - Complete URL with query parameters
   - **Domain**: Automatically detected from current request
   - **Endpoint**: `/provisioning/bootstrap/script`
   - **Query Parameters**:
     - `token`: JWT access token for authentication
     - `identity`: Router name to set
     - `api_port`: RouterOS API port
     - `interface`: WAN interface name

3. **`dst-path=codevertex.rsc`**
   - Destination file path on router filesystem
   - `.rsc` extension indicates RouterOS script
   - File stored in router's root directory

4. **`delay 2s`**
   - Pauses execution for 2 seconds
   - Ensures file download completes
   - Prevents script import failures

5. **`import codevertex.rsc`**
   - Executes the downloaded script
   - Runs all commands in sequence
   - Logs execution results

### The .rsc File (Bootstrap Script)

**What is an .rsc file?**
- RouterOS Script file containing configuration commands
- Plain text file with RouterOS CLI commands
- Supports comments (`;` prefix) and variables
- Executed line-by-line by RouterOS

**Bootstrap Script Content:**
```routeros
; ==================================================
; Codevertex ISP Billing System - Bootstrap Script
; ==================================================
; Generated: [TIMESTAMP]
; User ID: [USER_ID]
; Permissions: provisioning.execute, router.configure
; ==================================================

; Set router identity for easy identification
/system/identity/set name=[ROUTER_IDENTITY]

; Enable RouterOS API for remote management
/ip/service/set api disabled=no port=[API_PORT]

; Enable Winbox for GUI access
/ip/service/set winbox disabled=no

; Secure SSH with non-standard port
/ip/service/set ssh port=2222 disabled=no

; Disable insecure services
/ip/service/set telnet disabled=yes
/ip/service/set ftp disabled=yes

; Verify WAN interface exists
/interface/print where name=[INTERFACE]

; Create log entry for audit trail
:log info message="Codevertex bootstrap completed for [ROUTER_IDENTITY]"
:log info message="Provisioning token verified for user [USER_ID]"

; Router is now ready for full provisioning
```

**Why Two-Stage Provisioning?**

1. **Bootstrap Stage**:
   - Minimal configuration
   - Enables API access
   - Quick execution (< 5 seconds)
   - Allows backend connection

2. **Full Provisioning Stage**:
   - Complete service configuration
   - Complex network setup
   - Requires backend API connection
   - Live log streaming
   - Progress tracking

## Token-Based Authentication

### Security Architecture

The provisioning system uses JWT (JSON Web Token) for secure, time-limited access to provisioning scripts.

**Token Generation Flow:**

1. **User Request** → Frontend calls `/provisioning/bootstrap/command`
2. **Backend validates** user authentication and permissions
3. **AuthService creates** provisioning token:
   ```python
   token = create_provisioning_token(
       user_id=current_user.id,
       router_id=router_id,
       permissions=["provisioning.execute", "router.configure"],
       expires_in=3600  # 1 hour
   )
   ```
4. **Token embedded** in provisioning command URL
5. **Router executes** command and fetches script
6. **Backend verifies** token before serving script
7. **Script executed** on router with validated permissions

**Token Structure:**
```json
{
  "exp": 1735689600,  // Expiry timestamp
  "sub": "123",       // User ID
  "router_id": 0,     // Router ID (0 for new routers)
  "permissions": [
    "provisioning.execute",
    "router.configure"
  ],
  "purpose": "provisioning"  // Token type
}
```

**Token Security Features:**

1. **Time-Limited**: 1-hour expiry prevents unauthorized use
2. **Purpose-Specific**: Only valid for provisioning operations
3. **Permission-Based**: Limited to specific actions
4. **User-Bound**: Tied to requesting user's identity
5. **Single-Use Preferred**: Can be invalidated after use
6. **Audit Logged**: All token usage recorded

**Token Verification Process:**

```python
def verify_provisioning_token(token: str) -> Dict:
    try:
        # Decode JWT
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Verify purpose
        if payload.get("purpose") != "provisioning":
            raise UnauthorizedException("Invalid token purpose")
        
        # Check expiry (automatic in jwt.decode)
        # Check permissions
        required_permissions = ["provisioning.execute"]
        if not all(p in payload.get("permissions", []) for p in required_permissions):
            raise UnauthorizedException("Insufficient permissions")
        
        return payload
    except jwt.ExpiredSignatureError:
        raise UnauthorizedException("Token expired")
    except jwt.InvalidTokenError:
        raise UnauthorizedException("Invalid token")
```

**Why Token-Based Auth?**

- ✅ **No stored passwords in scripts**
- ✅ **Time-limited access** (auto-expires)
- ✅ **Audit trail** (who provisioned what)
- ✅ **Revocable** (can invalidate tokens)
- ✅ **Permission-based** (fine-grained control)
- ✅ **Router-accessible** (no complex auth flow)

## Live Streaming & WebSocket

### WebSocket Architecture

The system provides real-time provisioning updates via WebSocket connections, enabling users to monitor configuration progress as it happens.

**WebSocket Endpoint:**
```
ws://[DOMAIN]/provisioning/ws/[SESSION_ID]
wss://[DOMAIN]/provisioning/ws/[SESSION_ID]  # Secure WebSocket
```

**Connection Establishment:**

1. **Frontend initiates provisioning** → Backend returns `session_id`
2. **Frontend opens WebSocket** connection to `/provisioning/ws/{session_id}`
3. **Backend validates** session and establishes connection
4. **Provisioning begins** → Logs streamed in real-time
5. **Connection maintained** until provisioning completes or fails

**Message Types:**

```typescript
// Log Message
{
  type: "log",
  level: "info" | "success" | "warning" | "error",
  message: "Configuring bridge interfaces...",
  timestamp: "2025-01-21T12:34:56Z",
  step: "bridge_configuration"
}

// Status Update
{
  type: "status",
  status: "IN_PROGRESS" | "COMPLETED" | "FAILED",
  progress_percentage: 45,
  current_step: "Configuring Hotspot service",
  current_operation: "Adding Hotspot profile"
}

// Router Log (Direct Output)
{
  type: "router_log",
  command: "/interface bridge add name=codevertex-bridge",
  output: "added bridge interface",
  success: true
}

// Error Message
{
  type: "error",
  error_code: "BRIDGE_CREATE_FAILED",
  message: "Failed to create bridge interface",
  details: "Bridge name already exists",
  retry_available: true
}
```

**Frontend Implementation:**

```typescript
const LiveProvisioningLog = ({ sessionId }: { sessionId: string }) => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState<string>("CONNECTING");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Connect to WebSocket
    const ws = new WebSocket(`ws://localhost:8000/provisioning/ws/${sessionId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("CONNECTED");
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === "log") {
        setLogs(prev => [...prev, data]);
      } else if (data.type === "status") {
        setStatus(data.status);
      }
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      setStatus("ERROR");
    };

    ws.onclose = () => {
      setStatus("DISCONNECTED");
      // Auto-reconnect logic here
    };

    return () => {
      ws.close();
    };
  }, [sessionId]);

  // ... render logs
};
```

**Backend Streaming:**

```python
@router.websocket("/ws/{session_id}")
async def provisioning_stream(websocket: WebSocket, session_id: str):
    await websocket.accept()
    
    try:
        # Get provisioning session
        session = await get_session(session_id)
        
        # Stream logs in real-time
        async for log_entry in provision_router(session):
            await websocket.send_json({
                "type": "log",
                "level": log_entry.level,
                "message": log_entry.message,
                "timestamp": log_entry.timestamp.isoformat()
            })
        
        # Send completion message
        await websocket.send_json({
            "type": "status",
            "status": "COMPLETED",
            "progress_percentage": 100
        })
        
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })
    finally:
        await websocket.close()
```

**Log Coloring & Formatting:**

The frontend displays logs with color coding for better readability:
- 🟢 **Green (success)**: "Bridge configured successfully"
- 🔵 **Blue (info)**: "Scanning available interfaces..."
- 🟡 **Yellow (warning)**: "Port ether5 already in use, skipping"
- 🔴 **Red (error)**: "Failed to create DHCP pool"

**Auto-Scroll & Session Management:**

- **Auto-scroll**: Logs automatically scroll to bottom
- **Manual scroll**: User can scroll up to review earlier logs
- **Session persistence**: Logs retained until session cleanup
- **Reconnection**: Automatic reconnection if connection drops
- **Progress tracking**: Visual progress bar updates in real-time

## Frontend Integration

### Complete Integration Example

**Provisioning Page Component:**

```typescript
// app/(dashboard)/routers/provision/page.tsx
export default function ProvisionPage() {
  const [step, setStep] = useState(1);
  const { 
    generateProvisioningCommand, 
    scanDevice, 
    startProvisioning,
    isGeneratingCommand,
    isScanningDevice,
    deviceConnected,
    configuration,
    updateConfiguration
  } = useProvisioningStore();

  const handleStep1Next = async () => {
    await generateProvisioningCommand(0, identity, apiPort, interface);
    setStep(2);
  };

  const handleStep2Next = async () => {
    const scannedData = await scanDevice(routerId);
    setStep(3);
  };

  const handleStep3Next = async () => {
    const session = await startProvisioning(routerId, configuration);
    // Live logs will stream via WebSocket
  };

  return (
    <Card>
      <ProvisioningStepper currentStep={step} />
      
      {step === 1 && (
        <ConnectionStep
          onNext={handleStep1Next}
          isGenerating={isGeneratingCommand}
        />
      )}
      
      {step === 2 && (
        <DeviceDetailsStep
          onNext={handleStep2Next}
          deviceConnected={deviceConnected}
          isScanning={isScanningDevice}
        />
      )}
      
      {step === 3 && (
        <>
          <ServiceSetupStep
            onNext={handleStep3Next}
            configuration={configuration}
            onConfigChange={updateConfiguration}
          />
          <LiveProvisioningLog sessionId={sessionId} />
        </>
      )}
    </Card>
  );
}
```

**Provisioning Store (Zustand):**

```typescript
// lib/store/provisioning.ts
export const useProvisioningStore = create<ProvisioningState>((set, get) => ({
  configuration: {
    enableHotspot: true,
    enablePppoe: true,
    enableAntiSharing: true,
    useCustomSubnet: false,
    subnetAddress: '192.168.88.0',
    cidr: '24',
  },

  generateProvisioningCommand: async (routerId, identity, apiPort, interface) => {
    set({ isGeneratingCommand: true });
    try {
      const api = useApiStore.getState();
      const response = await api.makeRequest(`/provisioning/bootstrap/command?identity=${identity}&api_port=${apiPort}&interface=${interface}`);
      return response.command;
    } finally {
      set({ isGeneratingCommand: false });
    }
  },

  scanDevice: async (routerId) => {
    set({ isScanningDevice: true });
    try {
      const api = useApiStore.getState();
      const response = await api.makeRequest(`/provisioning/device/scan`, {
        method: 'POST',
        data: { router_id: routerId }
      });
      set({ deviceConnected: true });
      return response;
    } finally {
      set({ isScanningDevice: false });
    }
  },

  startProvisioning: async (routerId, configuration) => {
    const api = useApiStore.getState();
    return await api.makeRequest(`/provisioning/workflow`, {
      method: 'POST',
      data: {
        router_id: routerId,
        service_type: configuration.enableHotspot && configuration.enablePppoe ? 'both' : configuration.enableHotspot ? 'hotspot' : 'pppoe_server',
        configuration
      }
    });
  },
}));
```

## Backend Services

### Provisioning Service Structure

```
app/services/provisioning_service.py  # Main orchestrator
app/api/v1/provisioning/
  ├── bootstrap.py      # Command & script generation
  ├── network.py        # Network calculations
  ├── workflow.py       # Workflow management
  ├── stream.py         # WebSocket streaming
  └── device_scan.py    # Device scanning
```

### Key Service Methods

```python
class ProvisioningService:
    async def create_session(self, router_id: int, config: dict) -> Session:
        """Creates a new provisioning session"""
        
    async def execute_provisioning(self, session_id: str):
        """Executes the complete provisioning workflow"""
        
    async def stream_logs(self, session_id: str, websocket: WebSocket):
        """Streams provisioning logs via WebSocket"""
        
    async def rollback(self, session_id: str):
        """Rolls back failed provisioning"""
        
    async def get_session_status(self, session_id: str) -> SessionStatus:
        """Returns current session status and progress"""
```

## Command Generation

The system generates RouterOS commands dynamically based on:
- Router identity and network configuration
- Selected services (PPPoE, Hotspot, or both)
- Bridge port configuration
- Anti-sharing settings
- Custom subnet configuration

## RouterOS Interaction

The system uses the RouterOS API to:
- Execute configuration commands
- Monitor command execution status
- Handle errors and rollback operations
- Stream live logs to the frontend
- Parse router output for real-time feedback

## Error Handling and Rollback

- Automatic rollback on provisioning failures
- Configuration backup before changes
- Detailed error logging and reporting
- Manual retry capabilities
- Live error streaming to frontend

## Security Considerations

- Secure API communication with authentication
- Configuration validation before execution
- Rollback capabilities for failed operations
- Audit logging for all provisioning activities
- HTTPS-only script downloads
- Secure WebSocket connections

## Module Structure

### Backend Modules

1. **bootstrap.py** - Bootstrap command and script generation
2. **network.py** - Network calculation and validation
3. **workflow.py** - Main provisioning workflow management
4. **stream.py** - WebSocket streaming functionality
5. **live_streaming.py** - Live streaming manager

### Frontend Components

1. **ProvisioningStepper** - Step navigation component
2. **ConnectionStep** - Device connection configuration
3. **DeviceDetailsStep** - Provisioning command display
4. **ServiceSetupStep** - Service configuration
5. **LiveProvisioningLog** - Real-time log display

## Developer Tips

1. Always test provisioning commands in a lab environment first
2. Monitor the provisioning logs for detailed execution information
3. Use the rollback functionality for failed provisioning sessions
4. Ensure proper network connectivity before starting provisioning
5. Validate router compatibility before attempting provisioning
6. Test WebSocket connections for live streaming functionality
7. Verify .rsc script syntax before deployment
8. Monitor memory usage during live streaming sessions

## Troubleshooting

### Common Issues

1. **"device mode not allowed"** - Run `/system/device-mode update mode=advanced`
2. **Script download fails** - Ensure router has internet access and HTTPS is enabled
3. **WebSocket connection issues** - Check firewall settings and proxy configurations
4. **Import fails** - Verify script syntax and router compatibility

### Debug Mode

Enable debug logging to see detailed command execution:
```python
import logging
logging.getLogger('app.modules.provisioning').setLevel(logging.DEBUG)
```