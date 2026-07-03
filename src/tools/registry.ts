import { toolMetaSchema, type PermissionDecision, type ToolDefinition, type ToolRegistry } from '../types/tool.types.js';

export class BasicToolRegistry implements ToolRegistry {
  private readonly byName = new Map<string, ToolDefinition>();
  private readonly permissions = new Map<string, PermissionDecision>();
  private readonly aliasesByPrimary = new Map<string, string[]>();

  register(definition: ToolDefinition): void {
    const normalizedMeta = toolMetaSchema.parse(definition.meta);
    const normalized: ToolDefinition = {
      ...definition,
      meta: normalizedMeta
    };

    if (this.byName.has(normalized.meta.name)) {
      throw new Error(`Tool '${normalized.meta.name}' is already registered`);
    }

    this.setDefinition(normalized.meta.name, normalized);
    this.aliasesByPrimary.set(normalized.meta.name, [...normalized.meta.aliases]);
  }

  update(name: string, definition: ToolDefinition): void {
    const existing = this.getByName(name);
    if (!existing) {
      throw new Error(`Cannot update unknown tool '${name}'.`);
    }

    const primaryName = existing.meta.name;
    this.remove(primaryName);
    const merged: ToolDefinition = {
      ...definition,
      meta: {
        ...definition.meta,
        name: primaryName
      }
    };
    this.register(merged);
  }

  remove(name: string): void {
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

  getByName(name: string): ToolDefinition | undefined {
    return this.byName.get(name);
  }

  list(): ToolDefinition[] {
    return [...new Set(this.byName.values())];
  }

  getPermissionRequirement(name: string): PermissionDecision | undefined {
    return this.permissions.get(name);
  }

  private setDefinition(primaryName: string, definition: ToolDefinition): void {
    this.byName.set(primaryName, definition);
    this.permissions.set(primaryName, definition.meta.permissionRequirement ?? 'allow');

    for (const alias of definition.meta.aliases) {
      this.byName.set(alias, definition);
      this.permissions.set(alias, definition.meta.permissionRequirement ?? 'allow');
    }
  }
}
