/* Observe host names and module names only. No bodies, tokens, or socket payloads. */
send({event: "modules", arch: Process.arch, modules: Process.enumerateModules()
    .filter(m => /ssl|crypto|unity|il2cpp|houdini|anort/.test(m.name))
    .map(m => ({name: m.name, path: m.path}))});
const lookup = Process.getModuleByName("libc.so").findExportByName("getaddrinfo");
if (lookup) Interceptor.attach(lookup, {onEnter(args) {
    try { const host = args[0].readUtf8String();
        if (/hypergryph|hycdn/.test(host)) send({event: "dns", host});
    } catch (_) {}
}});
const connect = Process.getModuleByName("libc.so").findExportByName("connect");
if (connect) Interceptor.attach(connect, {onEnter(args) {
    try {
        const address = args[1];
        if (address.readU16() === 2) send({event: "connect-ipv4",
            port: (address.add(2).readU8() << 8) | address.add(3).readU8(),
            address: [4, 5, 6, 7].map(n => address.add(n).readU8()).join(".")});
    } catch (_) {}
}});
Java.perform(() => {
    const Inet = Java.use("java.net.InetAddress");
    const lookupJava = Inet.getAllByName.overload("java.lang.String");
    lookupJava.implementation = function(host) {
        if (/hypergryph|hycdn/.test(host)) send({event: "java-dns", host: host.toString()});
        return lookupJava.call(this, host);
    };
    send({event: "observation-ready"});
    try { send({event: "java-local-resolution-check", host: "ak-conf.hypergryph.com",
        addresses: Array.from(Inet.getAllByName("ak-conf.hypergryph.com")).map(a => a.getHostAddress().toString())});
    } catch (e) { send({event: "java-local-resolution-error", error: String(e)}); }
});
