import { type PermissionDecision, type ToolDefinition, type ToolRegistry } from '../types/tool.types.js';
export declare class BasicToolRegistry implements ToolRegistry {
    private readonly byName;
    private readonly permissions;
    private readonly aliasesByPrimary;
    register(definition: ToolDefinition): void;
    update(name: string, definition: ToolDefinition): void;
    remove(name: string): void;
    getByName(name: string): ToolDefinition | undefined;
    list(): ToolDefinition[];
    getPermissionRequirement(name: string): PermissionDecision | undefined;
    private setDefinition;
}
//# sourceMappingURL=registry.d.ts.map