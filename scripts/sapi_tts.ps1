param(
    [Parameter(Mandatory = $true, Position = 0)][string]$TextPath,
    [Parameter(Mandatory = $true, Position = 1)][string]$WavePath,
    [Parameter(Mandatory = $true, Position = 2)][string]$BoundariesPath,
    [Parameter(Mandatory = $true, Position = 3)][string]$Voice
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech

$text = [System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8)
if ([string]::IsNullOrWhiteSpace($text)) { throw 'narration text is empty' }

$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$words = [System.Collections.Generic.List[object]]::new()
try {
    if ($Voice -and $Voice -cne 'system-default') {
        $installed = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name })
        if ($installed -contains $Voice) {
            $synth.SelectVoice($Voice)
        } elseif ($installed.Count -gt 0) {
            $synth.SelectVoice($installed[0])
        }
    }

    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
        16000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $handler = {
        param($sender, $eventArgs)
        $words.Add([pscustomobject]@{
            text = $eventArgs.Text
            startMs = [int][Math]::Round($eventArgs.AudioPosition.TotalMilliseconds)
            charPosition = $eventArgs.CharacterPosition
        })
    }
    $synth.add_SpeakProgress($handler)
    $synth.SetOutputToWaveFile($WavePath, $format)
    $synth.Speak($text)
    $synth.SetOutputToNull()
    $stream = [System.IO.File]::OpenRead($WavePath)
    try {
        $reader = [System.IO.BinaryReader]::new($stream)
        $stream.Position = 12
        $byteRate = 0
        $dataBytes = 0
        while ($stream.Position + 8 -le $stream.Length) {
            $chunkId = [System.Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
            $chunkSize = $reader.ReadUInt32()
            $chunkStart = $stream.Position
            if ($chunkId -ceq 'fmt ') {
                $stream.Position = $chunkStart + 8
                $byteRate = $reader.ReadUInt32()
            } elseif ($chunkId -ceq 'data') {
                $dataBytes = $chunkSize
            }
            $stream.Position = $chunkStart + $chunkSize + ($chunkSize % 2)
        }
        if ($byteRate -le 0 -or $dataBytes -le 0) { throw 'invalid WAV chunks' }
        $durationMs = [int][Math]::Round(1000.0 * $dataBytes / $byteRate)
    } finally {
        $stream.Dispose()
    }

    $boundaries = @($words | Sort-Object -Property charPosition, startMs | Group-Object -Property charPosition | ForEach-Object { $_.Group[0] })
    $result = for ($i = 0; $i -lt $boundaries.Count; $i++) {
        $endMs = if ($i + 1 -lt $boundaries.Count) { $boundaries[$i + 1].startMs } else { $durationMs }
        $nextPosition = if ($i + 1 -lt $boundaries.Count) { $boundaries[$i + 1].charPosition } else { $text.Length }
        $wordText = $text.Substring($boundaries[$i].charPosition, $nextPosition - $boundaries[$i].charPosition).Trim()
        [pscustomobject]@{ text = $wordText; startMs = $boundaries[$i].startMs; endMs = $endMs }
    }
    [System.IO.File]::WriteAllText(
        $BoundariesPath,
        ($result | ConvertTo-Json -Compress),
        [System.Text.UTF8Encoding]::new($false)
    )
} finally {
    $synth.Dispose()
}
