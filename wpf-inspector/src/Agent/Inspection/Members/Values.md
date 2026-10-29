# Explicit value reads

The value reader resolves each segment against the current object's existing catalog.
It does not change catalog discovery or cache getter results between requests.

Enums use the framework's static `Enum.Format(type, value, "G")` formatter:
named values retain their names, Flags combinations use comma-separated symbolic
names (for example `Read, Write`), and unnamed values use decimal text. The
separate `numericValue` always contains the invariant underlying integer.
This is framework enum formatting, never an application object's ToString call.

Strings and characters with unpaired UTF-16 surrogates are unsupported, rather
than emitting invalid Unicode or silently changing application data. Valid
surrogate pairs count as one scalar and are never split by truncation.

Dependency-source metadata describes only the final dependency segment. A CLR
segment following a dependency segment does not inherit its source. Unavailable
variants omit the source, as required by the strict protocol.

Sensitive path names are checked before any getter or registry registration.
PasswordBox properties additionally use the actual declaring CLR type identity.
Name matching is deliberately conservative (including CancellationToken), cannot
identify every secret, and additional configured names never replace built-ins.
