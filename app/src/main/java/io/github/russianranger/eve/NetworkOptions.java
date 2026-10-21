package io.github.russianranger.eve;

/** Match Python's strict boolean/schema rules when selecting the native filter. */
final class NetworkOptions {
    final boolean fastSendto, traceStats;
    NetworkOptions(Object schema, Object fast, Object stats) {
        boolean supported = schema == null || ((schema instanceof Integer || schema instanceof Long) && ((Number) schema).longValue() == 1);
        fastSendto = supported && fast instanceof Boolean ? (Boolean) fast : true;
        traceStats = supported && stats instanceof Boolean ? (Boolean) stats : false;
    }
}
