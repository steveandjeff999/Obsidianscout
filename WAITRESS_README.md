# Server Configuration - Waitress vs Flask Development Server

This application can be configured to use either **Waitress** (production WSGI server) or the **Flask development server** with SSL support.

## 🚩 Configuration Flag

At the top of `run.py`, there's a simple flag that controls which server to use:

```python
# ============================================================================
# SERVER CONFIGURATION FLAG
# Set to True to use Waitress WSGI server, False to use Flask dev server with SSL
# ============================================================================
USE_WAITRESS = True  # Change this to False to use Flask development server with SSL
```

## 🚀 Server Options

### Option 1: Waitress WSGI Server (`USE_WAITRESS = True`)
**🎯 Recommended for production and most development**

**Features:**
- ✅ Production-ready WSGI server
- ✅ Better performance and stability
- ✅ Optimized threading (8 threads)
- ✅ Connection limiting (1000 concurrent)
- ✅ SocketIO polling mode (reliable)
- ⚠️  HTTP only (no SSL - use reverse proxy)

**When to use:**
- Production deployments
- Performance testing
- Stable development environment
- When you don't need direct SSL

### Option 2: Flask Development Server (`USE_WAITRESS = False`)
**🔧 Best for development when you need SSL/WebSockets**

**Features:**
- ✅ Full SSL/HTTPS support with auto-generated certificates
- ✅ Native WebSocket support (faster real-time features)
- ✅ Debug mode and detailed error messages
- ✅ Automatic SSL certificate generation
- ⚠️  Development only (not for production)

**When to use:**
- Testing SSL/HTTPS features
- Camera/QR code scanning (requires HTTPS)
- Full WebSocket performance testing
- Local development with HTTPS requirements

## 🔄 Switching Between Servers

### To use Waitress (Production):
1. Open `run.py`
2. Set `USE_WAITRESS = True`
3. Run `python run.py`
4. Server will start on `http://localhost:5000`

### To use Flask Dev Server with SSL:
1. Open `run.py` 
2. Set `USE_WAITRESS = False`
3. Run `python run.py`
4. Server will start on `https://localhost:5000`

## 📊 Comparison

| Feature | Waitress | Flask Dev + SSL |
|---------|----------|----------------|
| **Performance** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **Stability** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **SSL Support** | ❌ (use proxy) | ✅ Built-in |
| **WebSockets** | ⭐⭐⭐ (polling) | ⭐⭐⭐⭐⭐ |
| **Production Ready** | ✅ | ❌ |
| **Debug Features** | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Threading** | 8 threads | Single threaded |

## 🎯 Recommendations

- **For Production**: Always use `USE_WAITRESS = True`
- **For Development**: Use `USE_WAITRESS = True` unless you specifically need SSL
- **For SSL Testing**: Use `USE_WAITRESS = False` to test HTTPS features
- **For Real-time Features**: Both work, but Flask dev server has slightly better WebSocket performance

## 🔧 Technical Details

### Waitress Configuration
- **Threads**: 8 worker threads
- **Connections**: 1000 max concurrent
- **Transport**: SocketIO polling mode only
- **I/O**: Asyncore with polling for better performance
- **Buffer**: 64KB send buffer

### Flask Dev Server Configuration  
- **SSL**: Auto-generated self-signed certificates
- **Transport**: WebSocket + polling fallback
- **Debug**: Enabled in development
- **Reloader**: Disabled for stability
- **Certificate**: 10-year validity, localhost CN

## 🚨 Important Notes

- The flag only affects the **server choice**, not the application functionality
- All routes, features, and APIs work the same regardless of server
- SocketIO automatically adapts to the chosen server configuration
- SSL certificates are auto-generated when needed for Flask dev server
