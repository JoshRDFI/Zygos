import { toolMetaSchema } from '../types/tool.types.js';
export class BasicToolRegistry {
    byName = new Map();
    permissions = new Map();
    aliasesByPrimary = new Map();
    register(definition) {
        const normalizedMeta = toolMetaSchema.parse(definition.meta);
        const normalized = {
            ...definition,
            meta: normalizedMeta
        };
        if (this.byName.has(normalized.meta.name)) {
            throw new Error(`Tool '${normalized.meta.name}' is already registered`);
        }
        this.setDefinition(normalized.meta.name, normalized);
        this.aliasesByPrimary.set(normalized.meta.name, [...normalized.meta.aliases]);
    }
    update(name, definition) {
        const existing = this.getByName(name);
        if (!existing) {
            throw new Error(`Cannot update unknown tool '${name}'.`);
        }
        const primaryName = existing.meta.name;
        this.remove(primaryName);
        const merged = {
            ...definition,
            meta: {
                ...definition.meta,
                name: primaryName
            }
        };
        this.register(merged);
    }
    remove(name) {
        const existing = this.getByName(name);
        if (!existing) {
            return;
        }
        const primaryName = existing.meta.name;
        this.byName.delete(primaryName);
        this.permissions.delete(primaryName);
        const aliases = this.aliasesByPrimary.get(primaryName) ?? [];
        for (const alias of aliases) {
            this.byName.delete(alias);
            this.permissions.delete(alias);
        }
        this.aliasesByPrimary.delete(primaryName);
    }
    getByName(name) {
        return this.byName.get(name);
    }
    list() {
        return [...new Set(this.byName.values())];
    }
    getPermissionRequirement(name) {
        return this.permissions.get(name);
    }
    setDefinition(primaryName, definition) {
        this.byName.set(primaryName, definition);
        this.permissions.set(primaryName, definition.meta.permissionRequirement ?? 'allow');
        for (const alias of definition.meta.aliases) {
            this.byName.set(alias, definition);
            this.permissions.set(alias, definition.meta.permissionRequirement ?? 'allow');
        }
    }
}
//# sourceMappingURL=registry.js.map