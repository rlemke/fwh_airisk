# FFL examples — fwh_airisk

Each block compiles against the domain's own FFL:

```bash
fw ffl compile --check --primary <block.ffl> --library src/airisk/ffl/airisk.ffl \
    --library <facetwork>/facetwork/ffl/http.ffl
```

## 1. Refresh and rebuild

```ffl
namespace demo.refresh {
    use airisk.workflows

    workflow Refresh() => (output_dir: String, accelerating: Json) andThen {
        up = airisk.workflows.Update()
        yield Refresh(output_dir = up.output_dir, accelerating = up.accelerating)
    }
}
```

## 2. Just the data — plan, then fetch with the built-in `fw.http.Fetch`

`Sources` resolves this week's incident snapshot; `FetchAll` fans out at most three fetches at a time and returns paths in the order of `sources`.

```ffl
namespace demo.fetch {
    use airisk.data

    workflow FetchOnly() => (paths: Json, count: Int) andThen {
        plan = airisk.data.Sources()
        got = airisk.data.FetchAll(sources = plan.sources, user_agent = plan.user_agent)
        yield FetchOnly(paths = got.paths, count = plan.count)
    }
}
```

## 3. Fetch one source by hand — `$`-scoping into a Json parameter

```ffl
namespace demo.one {
    use airisk.data

    workflow FetchFirst() => (path: String) andThen {
        plan = airisk.data.Sources()
        one = airisk.data.FetchOne(source = plan.sources[0], user_agent = plan.user_agent)
        yield FetchFirst(path = one.path)
    }
}
```

## 4. Build from files already fetched — `after` for an invisible dependency

A second build re-reads the store that the first build wrote; no value flows between them, so the order is stated with `after`.

```ffl
namespace demo.rebuild {
    use airisk.data
    use airisk.site

    workflow BuildTwice() => (first: String, second: String) andThen {
        plan = airisk.data.Sources()
        got = airisk.data.FetchAll(sources = plan.sources, user_agent = plan.user_agent)
        a = airisk.site.Build(sources = plan.sources, paths = got.paths)
        b = airisk.site.Build(sources = plan.sources, paths = got.paths) after a
        yield BuildTwice(first = a.through, second = b.through)
    }
}
```

## 5. Decide on the result — `when` attached to the step it gates

Inside the cases, `$` is the `Update` step, so `$.through` is its return.

```ffl
namespace demo.alert {
    use airisk.workflows

    workflow Check() => (message: String) andThen {
        up = airisk.workflows.Update() andThen when {
            case $.through == "" => {
                yield Check(message = "no data")
            }
            case _ => {
                yield Check(message = "rebuilt through " ++ $.through)
            }
        }
    }
}
```

## 6. Cap the fetch fan-out from a parameter — `foreach … limit $.width`

```ffl
namespace demo.width {
    use airisk.data

    facet FetchWide(sources: Json, user_agent: String, width: Int = 0) => (paths: Json)
        andThen foreach s in $.sources limit $.width {
            one = airisk.data.FetchOne(source = $.s, user_agent = $.user_agent)
            yield FetchWide(paths += one.path)
        }

    workflow Wide(width: Int = 5) => (paths: Json) andThen {
        plan = airisk.data.Sources()
        got = FetchWide(sources = plan.sources, user_agent = plan.user_agent, width = $.width)
        yield Wide(paths = got.paths)
    }
}
```

## Syntax cheat sheet

| Construct | Example |
|---|---|
| Step | `plan = airisk.data.Sources()` |
| Reference | `plan.sources`, `$.width`, `$.s.url` |
| Fan-out, capped | `foreach s in $.sources limit 3 { … }` |
| Aggregate | `yield FetchAll(paths += one.path)` |
| Invisible order | `b = Build(…) after a` |
| Branch | `up = Update() andThen when { case $.through == "" => { … } case _ => { … } }` |
